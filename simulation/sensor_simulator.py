"""
sensor_simulator.py
-------------------
Simulates sensor readings (moisture, temperature, humidity, light_lux)
for each irrigation sector. Loaded and driven by the master controller;
also consumed by FaultSimulator.
"""

import json
import logging
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MOISTURE_OPEN_DELTA   = 0.5    # % per tick when valve is OPEN
MOISTURE_CLOSED_BASE  = 0.3    # % per tick base evaporation when CLOSED
TEMP_EVAP_FACTOR      = 0.01   # extra % evaporation per °C above 25 °C
NOISE_SIGMA_MOISTURE  = 0.08
NOISE_SIGMA_TEMP      = 0.05
NOISE_SIGMA_HUMIDITY  = 0.06
NOISE_SIGMA_LIGHT     = 15.0
LIGHT_BASELINE_LUX    = 35_000.0
SPIKE_MULTIPLIER      = 8.0    # noise_spike severity

VALID_RANGES = {
    "moisture":    (0.0,   100.0),
    "temperature": (-10.0, 60.0),
    "humidity":    (0.0,   100.0),
    "light_lux":   (0.0,   120_000.0),
}

FAULT_TYPES = {"stale", "invalid", "missing", "noise_spike"}


class SectorState:
    """Mutable per-sector sensor state."""

    def __init__(self, sector_cfg: Dict[str, Any]) -> None:
        self.sector_id: int   = sector_cfg["id"]
        self.node_id: str     = f"node_{sector_cfg['id']:02d}"
        self.moisture: float  = float(sector_cfg["initial_moisture"])
        self.temperature: float = float(sector_cfg["initial_temperature"])
        self.humidity: float  = float(sector_cfg["initial_humidity"])
        self.light_lux: float = LIGHT_BASELINE_LUX + random.gauss(0, 500)
        self.sequence_number: int = 0

        # fault flags
        self.fault: Optional[str] = None      # active fault type
        self.stale_until: float   = 0.0       # epoch; stale freeze until this time
        self.frozen_reading: Optional[Dict[str, Any]] = None   # last reading before freeze

    def snapshot(self) -> Dict[str, Any]:
        """Return a plain-dict snapshot of current values (no fault logic)."""
        return {
            "sector_id":       self.sector_id,
            "node_id":         self.node_id,
            "moisture":        round(self.moisture, 3),
            "temperature":     round(self.temperature, 3),
            "humidity":        round(self.humidity, 3),
            "light_lux":       round(self.light_lux, 1),
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "sequence_number": self.sequence_number,
        }


class SensorSimulator:
    """
    Simulates sensor nodes for all configured sectors.

    Parameters
    ----------
    config_path : str | Path
        Path to config/settings.json.
    irrigation_model : IrrigationModel, optional
        When supplied, valve state is read from the model on each update().
        Pass None to run standalone (all valves treated as CLOSED).
    """

    def __init__(
        self,
        config_path: str | Path = "config/settings.json",
        irrigation_model=None,
    ) -> None:
        self._config_path = Path(config_path)
        self._irrigation_model = irrigation_model  # may be None
        self._sectors: Dict[int, SectorState] = {}
        self._load_config()
        logger.info(
            "SensorSimulator initialised with %d sectors.", len(self._sectors)
        )

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        with open(self._config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        for s in cfg["sectors"]:
            self._sectors[s["id"]] = SectorState(s)
        logger.debug("Config loaded from %s", self._config_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, sector_id: Optional[int] = None) -> None:
        """
        Advance simulation by one tick.

        Called at every sensor_publish_interval.
        Applies moisture drift based on valve state, then adds Gaussian noise.
        Sectors marked 'stale' are skipped until stale_until expires.
        """
        items = (
            [(sector_id, self._sectors[sector_id])]
            if sector_id is not None and sector_id in self._sectors
            else list(self._sectors.items())
        )
        for sid, state in items:
            # Stale fault: freeze this sector until stale_until expires
            if state.fault == "stale":
                if time.monotonic() < state.stale_until:
                    logger.debug("Sector %d is stale — skipping update.", sid)
                    continue
                state.fault = None
                state.stale_until = 0.0
                state.frozen_reading = None
                logger.info("Sector %d: stale fault expired; resuming updates.", sid)

            valve_open = self._valve_is_open(sid)
            self._apply_moisture_drift(state, valve_open)
            self._drift_temperature(state)
            self._drift_humidity(state)
            self._drift_light(state)
            self.add_gaussian_noise(state)
            self._clamp(state)
            state.sequence_number += 1

    def add_gaussian_noise(self, state: SectorState) -> None:
        """
        Add realistic Gaussian noise to all sensor channels.
        Called internally by update(); may also be called externally for testing.
        """
        multiplier = SPIKE_MULTIPLIER if state.fault == "noise_spike" else 1.0
        state.moisture    += random.gauss(0, NOISE_SIGMA_MOISTURE  * multiplier)
        state.temperature += random.gauss(0, NOISE_SIGMA_TEMP      * multiplier)
        state.humidity    += random.gauss(0, NOISE_SIGMA_HUMIDITY   * multiplier)
        state.light_lux   += random.gauss(0, NOISE_SIGMA_LIGHT      * multiplier)

    def get_reading(self, sector_id: int) -> Optional[Dict[str, Any]]:
        """
        Return the current sensor reading for *sector_id*.

        Returns None for 'missing' fault.  Returns stale frozen snapshot
        for 'stale' fault.  Returns out-of-range values for 'invalid' fault.
        """
        state = self._get_state(sector_id)
        if state is None:
            logger.warning("get_reading: unknown sector_id=%d", sector_id)
            return None

        fault = state.fault

        if fault == "missing":
            logger.debug("Sector %d fault=missing — returning None.", sector_id)
            return None

        if fault == "stale" and state.frozen_reading is not None:
            if time.monotonic() < state.stale_until:
                # Return the frozen snapshot with the same timestamp to signal staleness
                logger.debug("Sector %d fault=stale — returning frozen reading.", sector_id)
                return dict(state.frozen_reading)
            state.fault = None
            state.stale_until = 0.0
            state.frozen_reading = None

        if fault == "invalid":
            reading = self._make_invalid_reading(state)
            state.fault = None   # one-shot: clear after emitting once
            logger.debug("Sector %d fault=invalid emitted, cleared.", sector_id)
            return reading

        return state.snapshot()

    def set_manual_value(self, sector_id: int, field: str, value: float) -> bool:
        """
        Override a sensor field directly (e.g. from the dashboard).

        Returns True on success, False if sector or field is unknown.
        """
        state = self._get_state(sector_id)
        if state is None:
            logger.warning("set_manual_value: unknown sector_id=%d", sector_id)
            return False
        if field not in VALID_RANGES:
            logger.warning("set_manual_value: unknown field '%s'", field)
            return False
        setattr(state, field, float(value))
        logger.info("Sector %d: manual override %s = %s", sector_id, field, value)
        return True

    def validate_reading(self, reading: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validate a reading dict against expected ranges.

        Returns (True, "ok") or (False, "<reason>").
        """
        if not isinstance(reading, dict):
            return False, "reading is None or not a dict"
        for field, (lo, hi) in VALID_RANGES.items():
            val = reading.get(field)
            if val is None:
                return False, f"missing field '{field}'"
            if isinstance(val, bool) or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                return False, f"non-numeric field '{field}': {val!r}"
            if not (lo <= float(val) <= hi):
                return False, (
                    f"'{field}' value {float(val):.3f} out of range [{lo}, {hi}]"
                )
        if not reading.get("timestamp"):
            return False, "missing timestamp"
        if reading.get("sequence_number") is None:
            return False, "missing sequence_number"
        return True, "ok"

    def inject_fault(self, sector_id: int, fault_type: str, duration_s: float = 30.0) -> bool:
        """
        Inject a sensor-level fault for *sector_id*.

        Parameters
        ----------
        fault_type : str
            One of 'stale', 'invalid', 'missing', 'noise_spike'.
        duration_s : float
            For 'stale' faults: how long to freeze the sector (seconds).

        Returns True on success.
        """
        if fault_type not in FAULT_TYPES:
            logger.error("inject_fault: unknown fault_type '%s'", fault_type)
            return False
        state = self._get_state(sector_id)
        if state is None:
            logger.warning("inject_fault: unknown sector_id=%d", sector_id)
            return False

        state.fault = fault_type
        if fault_type == "stale":
            state.stale_until = time.monotonic() + duration_s
            state.frozen_reading = state.snapshot()
            logger.info(
                "Sector %d: injected 'stale' fault for %.1fs.", sector_id, duration_s
            )
        elif fault_type == "invalid":
            logger.info("Sector %d: injected 'invalid' fault (one-shot).", sector_id)
        elif fault_type == "missing":
            logger.info("Sector %d: injected 'missing' fault.", sector_id)
        elif fault_type == "noise_spike":
            logger.info("Sector %d: injected 'noise_spike' fault.", sector_id)
        return True

    def clear_fault(self, sector_id: int) -> bool:
        """Clear any active fault for *sector_id*."""
        state = self._get_state(sector_id)
        if state is None:
            return False
        state.fault = None
        state.stale_until = 0.0
        state.frozen_reading = None
        logger.info("Sector %d: fault cleared.", sector_id)
        return True

    def get_all_sector_ids(self) -> List[int]:
        """Return sorted list of all configured sector IDs."""
        return sorted(self._sectors.keys())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_state(self, sector_id: int) -> Optional[SectorState]:
        return self._sectors.get(sector_id)

    def _valve_is_open(self, sector_id: int) -> bool:
        if self._irrigation_model is None:
            return False
        try:
            status = self._irrigation_model.get_status(sector_id)
            return status.get("valve_state") == "OPEN"
        except Exception:
            return False

    @staticmethod
    def _apply_moisture_drift(state: SectorState, valve_open: bool) -> None:
        if valve_open:
            state.moisture += MOISTURE_OPEN_DELTA
        else:
            # Evaporation increases with temperature above 25 °C
            extra = max(0.0, (state.temperature - 25.0) * TEMP_EVAP_FACTOR)
            state.moisture -= MOISTURE_CLOSED_BASE + extra

    @staticmethod
    def _drift_temperature(state: SectorState) -> None:
        state.temperature += random.gauss(0, 0.02)

    @staticmethod
    def _drift_humidity(state: SectorState) -> None:
        state.humidity += random.gauss(0, 0.03)

    @staticmethod
    def _drift_light(state: SectorState) -> None:
        # Simulate slow diurnal variation using a tiny random walk
        state.light_lux += random.gauss(0, 50)

    @staticmethod
    def _clamp(state: SectorState) -> None:
        lo_m, hi_m = VALID_RANGES["moisture"]
        lo_t, hi_t = VALID_RANGES["temperature"]
        lo_h, hi_h = VALID_RANGES["humidity"]
        lo_l, hi_l = VALID_RANGES["light_lux"]
        state.moisture    = max(lo_m, min(hi_m, state.moisture))
        state.temperature = max(lo_t, min(hi_t, state.temperature))
        state.humidity    = max(lo_h, min(hi_h, state.humidity))
        state.light_lux   = max(lo_l, min(hi_l, state.light_lux))

    @staticmethod
    def _make_invalid_reading(state: SectorState) -> Dict[str, Any]:
        """Return a reading with deliberately out-of-range values."""
        snap = state.snapshot()
        snap["moisture"]    = 150.0   # > 100 — clearly invalid
        snap["temperature"] = -50.0   # below -10 °C
        snap["humidity"]    = -5.0    # negative
        return snap
