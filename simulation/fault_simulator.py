"""
fault_simulator.py
------------------
High-level fault injection coordinator.

Wraps a SensorSimulator and an IrrigationModel and exposes a unified
interface for injecting, tracking, and clearing all categories of faults.
Used by integration tests, the dashboard "Fault Injection" panel, and
the scenario runner.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fault record
# ---------------------------------------------------------------------------

@dataclass
class FaultRecord:
    fault_id: str           # unique string key
    kind: str               # human-readable category
    sector_id: Optional[int]
    description: str
    injected_at: float      # time.monotonic()
    expires_at: Optional[float] = None   # None == indefinite


# ---------------------------------------------------------------------------
# FaultSimulator
# ---------------------------------------------------------------------------

class FaultSimulator:
    """
    Unified fault injector for sensors, valves, and the MQTT broker.

    Parameters
    ----------
    sensor_simulator : SensorSimulator
        The simulation's sensor layer (simulation.sensor_simulator).
    irrigation_model : IrrigationModel
        The simulation's irrigation layer (simulation.irrigation_model).
    """

    def __init__(self, sensor_simulator, irrigation_model) -> None:
        # Late-bound imports avoid circular dependency at module level
        from simulation.sensor_simulator import SensorSimulator
        from simulation.irrigation_model  import IrrigationModel

        if not isinstance(sensor_simulator, SensorSimulator):
            raise TypeError("sensor_simulator must be a SensorSimulator instance.")
        if not isinstance(irrigation_model, IrrigationModel):
            raise TypeError("irrigation_model must be an IrrigationModel instance.")

        self._sensor_sim   = sensor_simulator
        self._irrig_model  = irrigation_model

        self._faults: Dict[str, FaultRecord]   = {}
        self._offline_nodes: Dict[int, bool]   = {}   # sector_id -> True
        self._delayed_messages: Dict[int, float] = {}  # sector_id -> delay_s
        self._broker_disconnected: bool         = False

        # For delayed-message simulation: a background thread holds and
        # then re-releases readings per sector.
        self._delay_lock    = threading.Lock()
        self._delay_threads: Dict[int, threading.Thread] = {}

        logger.info("FaultSimulator ready.")

    # ------------------------------------------------------------------
    # Sensor faults
    # ------------------------------------------------------------------

    def inject_stale_data(self, sector_id: int, duration_s: float = 30.0) -> None:
        """
        Freeze the sensor readings for *sector_id* for *duration_s* seconds.

        The underlying SensorSimulator stops updating that sector; callers
        receive the same frozen snapshot until the duration expires or
        restore_all() is called.
        """
        self._sensor_sim.inject_fault(sector_id, "stale", duration_s=duration_s)
        self._register(
            fault_id=f"stale_{sector_id}",
            kind="stale_data",
            sector_id=sector_id,
            description=f"Stale data for {duration_s}s",
            expires_at=time.monotonic() + duration_s,
        )
        logger.warning(
            "FAULT: stale_data injected for sector %d (%.1fs).", sector_id, duration_s
        )

    def inject_invalid_data(self, sector_id: int) -> None:
        """
        Cause the sensor for *sector_id* to emit one out-of-range reading.

        The fault is automatically cleared by the SensorSimulator after the
        single bad reading is consumed.
        """
        self._sensor_sim.inject_fault(sector_id, "invalid")
        self._register(
            fault_id=f"invalid_{sector_id}",
            kind="invalid_data",
            sector_id=sector_id,
            description="Out-of-range reading (one-shot)",
        )
        logger.warning("FAULT: invalid_data injected for sector %d (one-shot).", sector_id)

    def inject_node_disconnect(self, sector_id: int) -> None:
        """
        Mark sector *sector_id*'s node as offline.

        The SensorSimulator will return None for every get_reading() call
        while the node is offline.  Call restore_all() or
        _restore_node(sector_id) to bring it back.
        """
        self._offline_nodes[sector_id] = True
        self._sensor_sim.inject_fault(sector_id, "missing")
        self._register(
            fault_id=f"disconnect_{sector_id}",
            kind="node_disconnect",
            sector_id=sector_id,
            description="Node marked offline; no readings published",
        )
        logger.warning("FAULT: node_disconnect injected for sector %d.", sector_id)

    def inject_delayed_message(self, sector_id: int, delay_s: float = 5.0) -> None:
        """
        Simulate a publish delay of *delay_s* seconds for sector *sector_id*.

        In a real system the MQTT publish would be held; here we record the
        delay so that the master controller (or a test) can retrieve it via
        get_active_faults() and apply the delay when timestamping readings.
        A background thread also fires after *delay_s* and clears the entry.
        """
        with self._delay_lock:
            self._delayed_messages[sector_id] = delay_s
        self._register(
            fault_id=f"delay_{sector_id}",
            kind="delayed_message",
            sector_id=sector_id,
            description=f"Publish delayed by {delay_s}s",
            expires_at=time.monotonic() + delay_s,
        )
        logger.warning(
            "FAULT: delayed_message injected for sector %d (%.1fs delay).",
            sector_id,
            delay_s,
        )
        # Spin up a daemon thread to auto-expire the delay
        t = threading.Thread(
            target=self._expire_delay,
            args=(sector_id, delay_s),
            daemon=True,
            name=f"fault-delay-{sector_id}",
        )
        with self._delay_lock:
            self._delay_threads[sector_id] = t
        t.start()

    def inject_valve_fault(self, sector_id: int, duration_s: float = 30.0) -> None:
        """
        Make the valve for *sector_id* ignore open/close commands for *duration_s* seconds.
        """
        self._irrig_model.simulate_valve_fault(sector_id, duration_s=duration_s)
        self._register(
            fault_id=f"valve_{sector_id}",
            kind="valve_fault",
            sector_id=sector_id,
            description=f"Valve ignores commands for {duration_s}s",
            expires_at=time.monotonic() + duration_s,
        )
        logger.warning(
            "FAULT: valve_fault injected for sector %d (%.1fs).", sector_id, duration_s
        )

    # ------------------------------------------------------------------
    # Broker fault
    # ------------------------------------------------------------------

    def inject_broker_disconnect(self) -> None:
        """
        Raise the broker-disconnect flag.

        The master MQTT client should detect this flag on its next loop
        iteration and treat it as a lost connection (reconnect logic /
        buffering).  Call restore_all() to clear.
        """
        self._broker_disconnected = True
        self._register(
            fault_id="broker_disconnect",
            kind="broker_disconnect",
            sector_id=None,
            description="MQTT broker simulated as disconnected",
        )
        logger.critical("FAULT: broker_disconnect injected — master should detect this.")

    @property
    def broker_disconnected(self) -> bool:
        """True when a broker-disconnect fault is currently active."""
        return self._broker_disconnected

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_all(self) -> None:
        """
        Clear every active fault and return all subsystems to normal operation.
        """
        # Restore sensor faults
        for sid in list(self._offline_nodes.keys()):
            self._sensor_sim.clear_fault(sid)
        self._offline_nodes.clear()

        for sid in self._sensor_sim.get_all_sector_ids():
            self._sensor_sim.clear_fault(sid)

        # Restore valve faults
        for sid in self._sensor_sim.get_all_sector_ids():
            self._irrig_model.clear_valve_fault(sid)

        # Restore broker
        self._broker_disconnected = False

        # Clear delayed messages
        with self._delay_lock:
            self._delayed_messages.clear()

        # Clear fault registry
        self._faults.clear()

        logger.info("FaultSimulator: all faults restored.")

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_active_faults(self) -> List[Dict[str, Any]]:
        """
        Return a list of currently active fault records (pruning expired ones).

        Each item is a dict with keys:
            fault_id, kind, sector_id, description, injected_at, expires_at.
        """
        now = time.monotonic()
        expired = [
            fid for fid, rec in self._faults.items()
            if rec.expires_at is not None and rec.expires_at <= now
        ]
        for fid in expired:
            del self._faults[fid]
            logger.debug("Fault '%s' expired and removed.", fid)

        return [
            {
                "fault_id":    rec.fault_id,
                "kind":        rec.kind,
                "sector_id":   rec.sector_id,
                "description": rec.description,
                "injected_at": rec.injected_at,
                "expires_at":  rec.expires_at,
                "age_s":       round(now - rec.injected_at, 2),
            }
            for rec in self._faults.values()
        ]

    def get_delay_for_sector(self, sector_id: int) -> Optional[float]:
        """
        Return the active publish delay (seconds) for *sector_id*, or None.
        Used by the master controller when constructing MQTT messages.
        """
        with self._delay_lock:
            return self._delayed_messages.get(sector_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _register(
        self,
        fault_id: str,
        kind: str,
        sector_id: Optional[int],
        description: str,
        expires_at: Optional[float] = None,
    ) -> None:
        self._faults[fault_id] = FaultRecord(
            fault_id=fault_id,
            kind=kind,
            sector_id=sector_id,
            description=description,
            injected_at=time.monotonic(),
            expires_at=expires_at,
        )

    def _expire_delay(self, sector_id: int, delay_s: float) -> None:
        """Background thread: remove delayed_message entry after delay_s."""
        time.sleep(delay_s)
        with self._delay_lock:
            self._delayed_messages.pop(sector_id, None)
            self._delay_threads.pop(sector_id, None)
        # Also remove from fault registry
        self._faults.pop(f"delay_{sector_id}", None)
        logger.info(
            "Sector %d: delayed_message fault expired after %.1fs.",
            sector_id,
            delay_s,
        )
