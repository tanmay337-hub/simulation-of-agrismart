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
SENSOR_FAULT_MODES = {"ok", "missing", "stale", "invalid", "noisy"}
CRISIS_MODES = {"normal", "heatwave", "rainstorm", "frost", "water_supply_failure", "broker_outage"}


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
        self.fault: Optional[str] = None      # active whole-node fault type
        self.stale_until: float   = 0.0       # epoch; stale freeze until this time
        self.frozen_reading: Optional[Dict[str, Any]] = None   # last reading before freeze

        # individual per-sensor fault modes & frozen values
        self.sensor_faults: Dict[str, str] = {
            "moisture": "ok",
            "temperature": "ok",
            "humidity": "ok",
            "light_lux": "ok",
        }
        self.frozen_sensor_values: Dict[str, float] = {}

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
        self._crisis_mode: str = "normal"
        self._load_config()
        logger.info(
            "SensorSimulator initialised with %d sectors.", len(self._sectors)
        )

    def set_crisis_mode(self, crisis: str) -> None:
        """Set farm-wide environmental crisis mode and apply immediate onset shift."""
        if crisis not in CRISIS_MODES or crisis == self._crisis_mode:
            return
        prev = self._crisis_mode
        self._crisis_mode = crisis
        self._apply_crisis_onset(crisis, prev)

    def _apply_crisis_onset(self, crisis: str, prev: str) -> None:
        """Immediately shift sensor readings when entering or leaving a crisis."""
        for state in self._sectors.values():
            if crisis == "heatwave":
                state.temperature = max(state.temperature + 8.5, 40.0 + random.uniform(-0.8, 1.8))
                state.humidity = min(state.humidity - 16.0, 21.0 + random.uniform(-2.0, 2.0))
                state.light_lux = max(state.light_lux, 76000.0 + random.uniform(-1500, 2500))
                state.moisture = max(5.0, state.moisture - 9.0)
            elif crisis == "rainstorm":
                state.moisture = min(100.0, state.moisture + 16.0)
                state.temperature = min(state.temperature, 21.5 + random.uniform(-0.8, 0.8))
                state.humidity = max(state.humidity, 93.0 + random.uniform(-1.5, 2.5))
                state.light_lux = min(state.light_lux, 4400.0 + random.uniform(-400, 400))
            elif crisis == "frost":
                state.temperature = 1.4 + random.uniform(-0.6, 0.6)
                state.humidity = max(state.humidity, 84.0 + random.uniform(-2.0, 2.0))
                state.light_lux = min(state.light_lux, 12000.0 + random.uniform(-800, 800))
            elif crisis == "normal" and prev in ("heatwave", "rainstorm", "frost"):
                state.temperature = max(25.0, min(32.0, state.temperature if 24.0 <= state.temperature <= 33.0 else 28.5 + random.uniform(-1.5, 2.0)))
                state.humidity = max(40.0, min(60.0, state.humidity if 38.0 <= state.humidity <= 65.0 else 49.0 + random.uniform(-3.0, 3.0)))
                state.light_lux = LIGHT_BASELINE_LUX + random.uniform(-800, 800)
            self._clamp(state)
            state.sequence_number += 1

    def set_sensor_fault(self, sector_id: int, sensor_name: str, mode: str) -> bool:
        """Set fault mode ('ok','missing','stale','invalid','noisy') on one sensor."""
        state = self._get_state(sector_id)
        if state is None or sensor_name not in state.sensor_faults or mode not in SENSOR_FAULT_MODES:
            return False
        state.sensor_faults[sensor_name] = mode
        if mode == "stale":
            state.frozen_sensor_values[sensor_name] = float(getattr(state, sensor_name))
        else:
            state.frozen_sensor_values.pop(sensor_name, None)
        return True

    def get_sensor_faults(self, sector_id: int) -> Dict[str, str]:
        state = self._get_state(sector_id)
        return dict(state.sensor_faults) if state else {}

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
            supply_ok = True
            if self._irrigation_model is not None and hasattr(self._irrigation_model, "get_status"):
                st_info = self._irrigation_model.get_status(sid)
                supply_ok = float(st_info.get("effective_flow_lpm", st_info.get("flow_rate_lpm", 2.0))) > 0.0
            self._apply_environmental_physics(state, valve_open and supply_ok)
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

        snap = state.snapshot()
        # Apply individual per-sensor faults without hiding healthy channels
        bad_vals = {"moisture": 148.0, "temperature": -45.0, "humidity": -12.0, "light_lux": -500.0}
        noisy_sigmas = {"moisture": 12.0, "temperature": 8.0, "humidity": 15.0, "light_lux": 18000.0}
        for s_name, s_mode in state.sensor_faults.items():
            if s_mode == "missing":
                snap[s_name] = None
            elif s_mode == "stale":
                snap[s_name] = round(state.frozen_sensor_values.get(s_name, snap[s_name]), 3)
            elif s_mode == "invalid":
                snap[s_name] = bad_vals[s_name]
            elif s_mode == "noisy":
                snap[s_name] = round(float(snap[s_name]) + random.gauss(0, noisy_sigmas[s_name]), 2)
        return snap

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
        for k in state.sensor_faults:
            state.sensor_faults[k] = "ok"
        state.frozen_sensor_values.clear()
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

    def _apply_environmental_physics(self, state: SectorState, irrigating_with_flow: bool) -> None:
        crisis = self._crisis_mode
        if crisis == "heatwave":
            if irrigating_with_flow:
                state.moisture += 0.35
            else:
                state.moisture -= 1.35
            state.temperature += (42.5 - state.temperature) * 0.22 + random.gauss(0, 0.05)
            state.humidity += (18.0 - state.humidity) * 0.20 + random.gauss(0, 0.06)
            state.light_lux += (78000.0 - state.light_lux) * 0.22
        elif crisis == "rainstorm":
            state.moisture += 1.65 + (0.45 if irrigating_with_flow else 0.0)
            state.temperature += (21.0 - state.temperature) * 0.18 + random.gauss(0, 0.04)
            state.humidity += (94.0 - state.humidity) * 0.25 + random.gauss(0, 0.05)
            state.light_lux += (4500.0 - state.light_lux) * 0.25
        elif crisis == "frost":
            if irrigating_with_flow:
                state.moisture += 0.45
            else:
                state.moisture -= 0.15
            state.temperature += (1.2 - state.temperature) * 0.25 + random.gauss(0, 0.04)
            state.humidity += (84.0 - state.humidity) * 0.18
            state.light_lux += (12000.0 - state.light_lux) * 0.20
        else:
            self._apply_moisture_drift(state, irrigating_with_flow)
            self._drift_temperature(state)
            self._drift_humidity(state)
            self._drift_light(state)

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
