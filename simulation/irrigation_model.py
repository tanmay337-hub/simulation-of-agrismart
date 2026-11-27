"""
irrigation_model.py
-------------------
Tracks valve states, flow rates, and water consumption per sector.
Consumed by SensorSimulator (moisture drift) and FaultSimulator (valve faults).
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_FLOW_RATE_LPM: float = 2.0        # litres per minute per sector
VALVE_FAULT_DURATION_S: float = 30.0      # seconds a faulty valve ignores commands
SECONDS_PER_MINUTE: float = 60.0


VALVE_FAULT_MODES = {"normal", "stuck_closed", "stuck_open", "no_ack", "leak"}


class _SectorValve:
    """Internal valve + metering state for one sector."""

    __slots__ = (
        "sector_id",
        "valve_state",
        "flow_rate_lpm",
        "water_consumed_litres",
        "last_command_time",
        "last_ack_time",
        "ack_pending",
        "_fault_until",   # monotonic epoch: valve ignores commands until this time
        "fault_mode",     # normal | stuck_closed | stuck_open | no_ack | leak
    )

    def __init__(self, sector_id: int, flow_rate_lpm: float) -> None:
        self.sector_id: int             = sector_id
        self.valve_state: str           = "CLOSED"
        self.flow_rate_lpm: float       = flow_rate_lpm
        self.water_consumed_litres: float = 0.0
        self.last_command_time: Optional[float] = None
        self.last_ack_time: Optional[float]     = None
        self.ack_pending: bool          = False
        self._fault_until: float        = 0.0
        self.fault_mode: str            = "normal"

    @property
    def is_faulted(self) -> bool:
        return time.monotonic() < self._fault_until or self.fault_mode != "normal"


class IrrigationModel:
    """
    Models the irrigation valves and water accounting for every sector.

    Parameters
    ----------
    flow_rate_lpm : float
        Default flow rate (litres / minute) applied to all sectors unless
        overridden per-sector via set_flow_rate().
    sector_ids : list[int]
        Sector IDs to pre-populate.  If empty, sectors are created on demand
        when open_valve / close_valve is first called.
    """

    def __init__(
        self,
        flow_rate_lpm: float = DEFAULT_FLOW_RATE_LPM,
        sector_ids: Optional[List[int]] = None,
    ) -> None:
        self._default_flow_rate = flow_rate_lpm
        self._sectors: Dict[int, _SectorValve] = {}
        self.water_supply_failed: bool = False
        for sid in (sector_ids or []):
            self._ensure_sector(sid)
        logger.info(
            "IrrigationModel initialised: %d sectors, default flow %.2f lpm.",
            len(self._sectors),
            flow_rate_lpm,
        )

    def set_valve_fault_mode(self, sector_id: int, mode: str) -> bool:
        """Set persistent granular valve fault mode."""
        if mode not in VALVE_FAULT_MODES:
            return False
        valve = self._ensure_sector(sector_id)
        valve.fault_mode = mode
        if mode == "normal":
            valve._fault_until = 0.0
        return True

    def set_water_supply_failed(self, failed: bool) -> None:
        self.water_supply_failed = bool(failed)

    # ------------------------------------------------------------------
    # Valve control
    # ------------------------------------------------------------------

    def open_valve(self, sector_id: int) -> bool:
        """
        Open the valve for *sector_id*.

        Returns False (and logs a warning) when the valve is currently faulted.
        """
        valve = self._ensure_sector(sector_id)
        now = time.monotonic()
        if time.monotonic() < valve._fault_until or valve.fault_mode == "stuck_closed":
            logger.warning("Sector %d: open_valve failed — valve fault (%s).", sector_id, valve.fault_mode)
            return False
        if valve.fault_mode == "no_ack":
            # Valve physically changes or attempts to move, but ACK must be suppressed by node
            valve.valve_state = "OPEN"
            valve.last_command_time = now
            valve.ack_pending = True
            return False
        if valve.valve_state == "OPEN":
            logger.debug("Sector %d: valve already OPEN.", sector_id)
            return True
        valve.valve_state = "OPEN"
        valve.last_command_time = now
        valve.last_ack_time = now       # local simulation: immediate ack
        valve.ack_pending = False
        logger.info("Sector %d: valve OPENED.", sector_id)
        return True

    def close_valve(self, sector_id: int) -> bool:
        """
        Close the valve for *sector_id*.

        Returns False when the valve is currently faulted.
        """
        valve = self._ensure_sector(sector_id)
        now = time.monotonic()
        if time.monotonic() < valve._fault_until or valve.fault_mode == "stuck_open":
            logger.warning("Sector %d: close_valve failed — valve fault (%s).", sector_id, valve.fault_mode)
            return False
        if valve.fault_mode == "no_ack":
            valve.valve_state = "CLOSED"
            valve.last_command_time = now
            valve.ack_pending = True
            return False
        if valve.valve_state == "CLOSED":
            logger.debug("Sector %d: valve already CLOSED.", sector_id)
            return True
        valve.valve_state = "CLOSED"
        valve.last_command_time = now
        valve.last_ack_time = now
        valve.ack_pending = False
        logger.info("Sector %d: valve CLOSED.", sector_id)
        return True

    # ------------------------------------------------------------------
    # Time-step
    # ------------------------------------------------------------------

    def effective_flow_lpm(self, valve: _SectorValve) -> float:
        if self.water_supply_failed:
            return 0.0
        if valve.valve_state == "OPEN":
            return valve.flow_rate_lpm
        if valve.fault_mode == "leak":
            return round(valve.flow_rate_lpm * 0.4, 2)
        return 0.0

    def tick(self, elapsed_seconds: float) -> None:
        """
        Advance the model by *elapsed_seconds*.

        Accumulates water consumption for every OPEN or leaking valve.
        """
        if elapsed_seconds <= 0:
            return
        for valve in self._sectors.values():
            eff = self.effective_flow_lpm(valve)
            if eff > 0.0:
                litres = eff * (elapsed_seconds / SECONDS_PER_MINUTE)
                valve.water_consumed_litres += litres

    # ------------------------------------------------------------------
    # Status / query
    # ------------------------------------------------------------------

    def get_status(self, sector_id: int) -> Dict[str, Any]:
        """
        Return the current status dict for *sector_id*.
        """
        valve = self._ensure_sector(sector_id)
        eff_flow = self.effective_flow_lpm(valve)
        return {
            "sector_id":              valve.sector_id,
            "valve_state":            valve.valve_state,
            "flow_rate_lpm":          valve.flow_rate_lpm,
            "effective_flow_lpm":     eff_flow,
            "water_consumed_litres":  round(valve.water_consumed_litres, 4),
            "is_irrigating":          valve.valve_state == "OPEN",
            "last_command_time":      valve.last_command_time,
            "last_ack_time":          valve.last_ack_time,
            "ack_pending":            valve.ack_pending,
            "is_faulted":             valve.is_faulted,
            "fault_mode":             valve.fault_mode,
        }

    def get_total_water_consumed(self) -> float:
        """Return farm-wide total water consumption in litres."""
        total = sum(v.water_consumed_litres for v in self._sectors.values())
        return round(total, 4)

    def get_all_statuses(self) -> List[Dict[str, Any]]:
        """Return status dicts for every registered sector, sorted by sector_id."""
        return [self.get_status(sid) for sid in sorted(self._sectors.keys())]

    # ------------------------------------------------------------------
    # Fault injection
    # ------------------------------------------------------------------

    def simulate_valve_fault(self, sector_id: int, duration_s: float = VALVE_FAULT_DURATION_S) -> None:
        """
        Make the valve for *sector_id* ignore open/close commands for *duration_s* seconds.

        The valve remains in its current state for the fault duration.
        """
        valve = self._ensure_sector(sector_id)
        valve._fault_until = time.monotonic() + duration_s
        logger.warning(
            "Sector %d: valve fault injected — commands ignored for %.1fs.",
            sector_id,
            duration_s,
        )

    def clear_valve_fault(self, sector_id: int) -> None:
        """Immediately clear any active valve fault for *sector_id*."""
        valve = self._ensure_sector(sector_id)
        valve._fault_until = 0.0
        valve.fault_mode = "normal"
        logger.info("Sector %d: valve fault cleared.", sector_id)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def set_flow_rate(self, sector_id: int, flow_rate_lpm: float) -> None:
        """Override the flow rate (litres/min) for a specific sector."""
        valve = self._ensure_sector(sector_id)
        valve.flow_rate_lpm = flow_rate_lpm
        logger.info("Sector %d: flow rate set to %.2f lpm.", sector_id, flow_rate_lpm)

    def reset_water_consumed(self, sector_id: Optional[int] = None) -> None:
        """
        Reset water consumption counters.

        If *sector_id* is None, resets all sectors.
        """
        if sector_id is None:
            for valve in self._sectors.values():
                valve.water_consumed_litres = 0.0
            logger.info("All sectors: water consumption reset.")
        else:
            valve = self._ensure_sector(sector_id)
            valve.water_consumed_litres = 0.0
            logger.info("Sector %d: water consumption reset.", sector_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_sector(self, sector_id: int) -> _SectorValve:
        """Return (and lazily create) the _SectorValve for *sector_id*."""
        if sector_id not in self._sectors:
            self._sectors[sector_id] = _SectorValve(sector_id, self._default_flow_rate)
            logger.debug("Sector %d: auto-created on first access.", sector_id)
        return self._sectors[sector_id]
