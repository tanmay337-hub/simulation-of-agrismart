"""
raspberry_pi_master.py — Central coordinator for the Virtual Smart Agriculture
Irrigation System.

HARDWARE REPLACEMENT GUIDE:
  - Runs unchanged on a real Raspberry Pi 5 (Python 3.9+ with Mosquitto on LAN).
  - Update config/settings.json -> mqtt.broker from "localhost" to the Pi's
    LAN IP (or keep "localhost" if Mosquitto runs on the Pi itself).

Responsibilities:
  - Subscribes to all 4 sector sensor, status, and command topics via MQTT.
  - Validates incoming telemetry (rejects invalid or stale data).
  - Runs the rule-based DecisionEngine every 5 s for sectors in AUTO mode.
  - Publishes valve commands (never retaining OPEN commands) and tracks ACKs.
  - Persists telemetry, commands, ACKs, alerts, and events to SQLite.
  - Publishes master heartbeat to farm/system/status every 5 s.
  - Writes system state to data/system_state.json every 5 s for the dashboard.
  - Handles graceful shutdown on SIGINT / SIGTERM.
"""

import json
import logging
import math
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from master.database import Database  # noqa: E402
from master.decision_engine import DecisionEngine  # noqa: E402
from master.mqtt_manager import MQTTManager  # noqa: E402

SECTORS = [1, 2, 3, 4]
SETTINGS_PATH = os.path.join(_PROJECT_ROOT, "config", "settings.json")
SIM_CONTROL_PATH = os.path.join(_PROJECT_ROOT, "data", "sim_control.json")
LOGS_DIR = os.path.join(_PROJECT_ROOT, "logs")
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
STATE_FILE = os.path.join(DATA_DIR, "system_state.json")
MASTER_LOG = os.path.join(LOGS_DIR, "master.log")

LOOP_INTERVAL = 5
ACK_CHECK_INTERVAL = 10
ACK_TIMEOUT = 15
ALERT_COOLDOWN_S = 60.0

VALID_RANGES = {
    "moisture": (0.0, 100.0),
    "temperature": (-10.0, 60.0),
    "humidity": (0.0, 100.0),
    "light_lux": (0.0, 120_000.0),
}

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

logger = logging.getLogger("master")
logger.setLevel(logging.INFO)
logger.handlers.clear()

_fmt = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_fmt)
_file_handler = logging.FileHandler(MASTER_LOG, encoding="utf-8")
_file_handler.setFormatter(_fmt)
logger.addHandler(_console_handler)
logger.addHandler(_file_handler)


def _load_settings() -> dict[str, Any]:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
            settings = json.load(fh)
        logger.info("Settings loaded from %s", SETTINGS_PATH)
        return settings
    except FileNotFoundError:
        logger.error("settings.json not found at %s. Using defaults.", SETTINGS_PATH)
        return {
            "mqtt": {"broker": "localhost", "port": 1883, "keepalive": 60},
            "thresholds": {
                "moisture_start": 30,
                "moisture_stop": 55,
                "temp_alert": 35,
                "humidity_alert": 35,
            },
            "flow_rate_lpm": 2.0,
            "sensor_publish_interval": 5,
            "stale_data_timeout": 30,
            "node_offline_timeout": 60,
            "failsafe_timeout": 90,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return time.monotonic()


def _validate_telemetry(data: Any) -> tuple[bool, str]:
    """Validate an inbound telemetry payload before trusting it for decisions."""
    if not isinstance(data, dict):
        return False, "Telemetry payload is not a JSON object"
    for field, (lo, hi) in VALID_RANGES.items():
        val = data.get(field)
        if val is None:
            return False, f"Missing required field '{field}'"
        if isinstance(val, bool) or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
            return False, f"Non-numeric field '{field}': {val!r}"
        if not (lo <= float(val) <= hi):
            return False, f"'{field}' value {float(val):.2f} out of range [{lo}, {hi}]"
    if not data.get("timestamp"):
        return False, "Missing timestamp"
    if data.get("sequence_number") is None:
        return False, "Missing sequence_number"
    return True, "ok"


class RaspberryPiMaster:
    """Central coordinator for the Smart Agriculture Irrigation System."""

    def __init__(self) -> None:
        self._settings = _load_settings()
        self._mqtt_cfg = self._settings.get("mqtt", {})
        self._stale_data_timeout = float(self._settings.get("stale_data_timeout", 30))
        self._node_offline_timeout = float(self._settings.get("node_offline_timeout", 60))
        self._flow_rate_lpm = float(self._settings.get("flow_rate_lpm", 2.0))

        self._lock = threading.Lock()
        self._sector_state: dict[int, dict[str, Any]] = {
            sid: {
                "last_reading": None,
                "last_seen": None,
                "last_fresh_ts": None,
                "last_seq": None,
                "last_reading_ts": None,
                "valve_state": "CLOSED",
                "desired_valve_state": "CLOSED",
                "flow_rate_lpm": self._flow_rate_lpm,
                "water_consumed_litres": 0.0,
                "mode": "AUTO",
                "pending_cmds": {},
                "node_online": False,
                "stale": False,
                "reading_valid": True,
                "invalid_reason": "",
            }
            for sid in SECTORS
        }

        self._alert_count = 0
        self._last_alert_sent: dict[tuple[Any, str], float] = {}
        self._broker_connected = False
        self._running = False

        self._decision_engine: DecisionEngine | None = None
        self._mqtt: MQTTManager | None = None
        self._db: Database | None = None
        self._last_ack_check = _now_ts()
        self._main_thread: threading.Thread | None = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def start(self) -> None:
        """Connect sub-systems and launch the control loop."""
        logger.info("Starting RaspberryPiMaster ...")
        self._decision_engine = DecisionEngine(settings_path=SETTINGS_PATH)
        self._db = Database()
        self._db.insert_event("SYSTEM_START", "Raspberry Pi Master started.", timestamp=_now_iso())

        broker = self._mqtt_cfg.get("broker", "localhost")
        port = int(self._mqtt_cfg.get("port", 1883))
        keepalive = int(self._mqtt_cfg.get("keepalive", 60))

        self._mqtt = MQTTManager(
            broker=broker,
            port=port,
            client_id=f"rpi_master_{uuid.uuid4().hex[:6]}",
            on_message_callback=self._on_message,
            on_connect_callback=self._on_connect,
            on_disconnect_callback=self._on_disconnect,
            keepalive=keepalive,
        )

        # Register subscriptions so MQTTManager restores them automatically on reconnects
        for sid in SECTORS:
            self._mqtt.subscribe(f"farm/sector{sid}/sensors", qos=1)
            self._mqtt.subscribe(f"farm/sector{sid}/status", qos=1)
            self._mqtt.subscribe(f"farm/sector{sid}/command", qos=1)
        self._mqtt.subscribe("farm/system/alerts", qos=1)
        self._mqtt.subscribe("farm/system/config", qos=1)
        self._mqtt.subscribe("farm/system/control", qos=1)

        if not self._mqtt.connect():
            logger.warning("Initial MQTT connect did not complete — starting reconnect loop.")
            self._mqtt.reconnect()

        self._running = True
        self._write_state_file()

        self._main_thread = threading.Thread(
            target=self._main_loop, name="master-loop", daemon=True
        )
        self._main_thread.start()
        logger.info("RaspberryPiMaster running. Press Ctrl+C to stop.")

    def shutdown(self) -> None:
        """Graceful shutdown: close all valves, mark offline, disconnect MQTT."""
        if not self._running:
            return
        self._running = False
        logger.info("Shutdown initiated — closing all valves ...")

        for sid in SECTORS:
            try:
                self._publish_command(sid, "CLOSE", source="master_shutdown")
            except Exception as exc:
                logger.error("Error closing valve for sector %s: %s", sid, exc)

        self._write_state_file(master_online=False)
        time.sleep(0.8)

        if self._mqtt:
            try:
                self._mqtt.publish(
                    "farm/system/status",
                    {"master_online": False, "timestamp": _now_iso()},
                    qos=0,
                    retain=False,
                )
                self._mqtt.disconnect()
            except Exception as exc:
                logger.error("Error disconnecting MQTT: %s", exc)

        if self._db:
            try:
                self._db.insert_event("SYSTEM_STOP", "Raspberry Pi Master stopped cleanly.", timestamp=_now_iso())
                self._db.close()
            except Exception as exc:
                logger.error("Error closing database: %s", exc)

        logger.info("RaspberryPiMaster shutdown complete.")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        logger.info("Received signal %s — shutting down.", signum)
        self.shutdown()
        sys.exit(0)

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_connect(self) -> None:
        self._broker_connected = True
        logger.info("Master connected to MQTT broker.")
        if self._db:
            self._db.insert_event("BROKER_CONNECTED", "Master connected to MQTT broker.", timestamp=_now_iso())

    def _on_disconnect(self) -> None:
        self._broker_connected = False
        logger.warning("Master disconnected from MQTT broker.")
        if self._db:
            self._db.insert_event("BROKER_DISCONNECTED", "Master lost connection to MQTT broker.", timestamp=_now_iso())

    def _on_message(self, topic: str, payload: Any) -> None:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                logger.warning("Unparseable JSON on %s: %s", topic, exc)
                return
        elif isinstance(payload, dict):
            data = payload
        else:
            logger.warning("Unexpected payload type on %s: %s", topic, type(payload))
            return

        parts = topic.split("/")
        if len(parts) != 3 or parts[0] != "farm":
            return

        target, msg_type = parts[1], parts[2]
        if target.startswith("sector"):
            try:
                sid = int(target[len("sector"):])
            except ValueError:
                return
            if sid not in SECTORS:
                return
            if msg_type == "sensors":
                self._handle_sensor_message(sid, data)
            elif msg_type == "status":
                self._handle_status_message(sid, data)
            elif msg_type == "command":
                self._handle_observed_command(sid, data)
        elif target == "system":
            if msg_type == "alerts":
                self._handle_system_alert(data)
            elif msg_type == "config":
                self._handle_config_update(data)
            elif msg_type == "control":
                self._handle_control_message(data)

    def _handle_sensor_message(self, sid: int, data: dict[str, Any]) -> None:
        now = _now_ts()
        valid, reason = _validate_telemetry(data)

        if not valid:
            logger.warning("Sector %s INVALID telemetry rejected: %s (%s)", sid, reason, data)
            with self._lock:
                state = self._sector_state[sid]
                state["last_seen"] = now
                state["node_online"] = True
                state["reading_valid"] = False
                state["invalid_reason"] = reason
            self._raise_alert(
                sid,
                "invalid_sensor_data",
                f"Sector {sid} sent invalid telemetry ({reason}); excluded from decisions.",
                severity="WARNING",
            )
            if self._db:
                self._db.insert_event(
                    "FAULT",
                    f"Invalid telemetry on Sector {sid}: {reason}",
                    timestamp=_now_iso(),
                    sector_id=sid,
                    payload=data,
                )
            return

        seq = data.get("sequence_number")
        reading_ts = str(data.get("timestamp"))

        # Check whether the node is re-sending the exact same frozen reading (stale)
        is_duplicate_reading = False
        with self._lock:
            state = self._sector_state[sid]
            if state["last_seq"] is not None and seq == state["last_seq"] and reading_ts == state["last_reading_ts"]:
                is_duplicate_reading = True
            else:
                state["last_fresh_ts"] = now
                state["last_seq"] = seq
                state["last_reading_ts"] = reading_ts
                state["stale"] = False

            state["last_seen"] = now
            state["node_online"] = True
            state["reading_valid"] = True
            state["invalid_reason"] = ""
            state["last_reading"] = data

            # Update flow/water metering and confirmed valve state from telemetry if no command pending
            if "flow_rate_lpm" in data:
                state["flow_rate_lpm"] = float(data["flow_rate_lpm"])
            if "water_consumed_litres" in data:
                state["water_consumed_litres"] = float(data["water_consumed_litres"])
            if not state["pending_cmds"] and data.get("valve_state") in ("OPEN", "CLOSED"):
                state["valve_state"] = data["valve_state"]

        if is_duplicate_reading:
            logger.debug("Sector %s repeated frozen reading seq=%s ts=%s", sid, seq, reading_ts)
        else:
            if self._db:
                self._db.resolve_alerts(sector_id=sid, alert_type="node_offline")
                self._db.resolve_alerts(sector_id=sid, alert_type="stale_data")
                self._db.resolve_alerts(sector_id=sid, alert_type="invalid_sensor_data")
                self._db.insert_sensor_reading(sector_id=sid, reading_dict=data, timestamp=_now_iso())

    def _handle_status_message(self, sid: int, data: dict[str, Any]) -> None:
        cmd_id = data.get("cmd_id")
        status = data.get("status", "UNKNOWN")
        valve_state = data.get("valve_state")
        reason = data.get("reason", "")

        with self._lock:
            state = self._sector_state[sid]
            if "flow_rate_lpm" in data:
                state["flow_rate_lpm"] = float(data["flow_rate_lpm"])
            if "water_consumed_litres" in data:
                state["water_consumed_litres"] = float(data["water_consumed_litres"])

            if cmd_id and cmd_id in state["pending_cmds"]:
                pending = state["pending_cmds"].pop(cmd_id)
                latency = _now_ts() - pending["sent_at"]
                logger.info(
                    "Sector %s ACK confirmed: cmd_id=%s status=%s valve=%s latency=%.2fs",
                    sid,
                    cmd_id,
                    status,
                    valve_state,
                    latency,
                )
            if status in ("ACCEPTED", "ONLINE") and valve_state in ("OPEN", "CLOSED"):
                state["valve_state"] = valve_state
                state["last_seen"] = _now_ts()
                state["node_online"] = True
            elif status == "OFFLINE":
                state["node_online"] = False
                if valve_state in ("OPEN", "CLOSED"):
                    state["valve_state"] = valve_state

        if self._db and cmd_id and cmd_id not in ("boot",):
            self._db.insert_ack(
                cmd_id=str(cmd_id),
                sector_id=sid,
                status=str(status),
                timestamp=_now_iso(),
                valve_state=valve_state,
                reason=reason,
            )
            self._db.insert_event(
                "ACK",
                f"Sector {sid} ACK {status} (valve={valve_state}): {reason}",
                timestamp=_now_iso(),
                sector_id=sid,
                payload=data,
            )

    def _handle_observed_command(self, sid: int, data: dict[str, Any]) -> None:
        """Track commands published directly by the dashboard so ACKs and timeouts match."""
        source = data.get("source", "unknown")
        if source == "master" or source == "master_shutdown":
            return
        cmd_id = data.get("cmd_id")
        action = data.get("action")
        if not cmd_id or not action:
            return
        with self._lock:
            self._sector_state[sid]["pending_cmds"][cmd_id] = {
                "action": action,
                "sent_at": _now_ts(),
            }
            if action in ("OPEN", "CLOSE", "EMERGENCY_OFF"):
                self._sector_state[sid]["desired_valve_state"] = (
                    "OPEN" if action == "OPEN" else "CLOSED"
                )
        if self._db:
            self._db.insert_command(str(cmd_id), sid, str(action), timestamp=_now_iso(), source=str(source))
            event_type = "EMERGENCY" if action == "EMERGENCY_OFF" else "COMMAND"
            self._db.insert_event(
                event_type,
                f"Dashboard {action} command published to Sector {sid}",
                timestamp=_now_iso(),
                sector_id=sid,
                payload=data,
            )

    def _handle_system_alert(self, data: dict[str, Any]) -> None:
        if data.get("source") == "master":
            return
        sid = data.get("sector_id")
        alert_type = data.get("alert_type", "node_alert")
        message = data.get("message", str(data))
        severity = data.get("severity", "CRITICAL")
        with self._lock:
            self._alert_count += 1
        logger.warning("Node/System alert received (sector=%s): %s", sid, message)
        if self._db:
            self._db.insert_alert(sid, alert_type, message, timestamp=_now_iso(), severity=severity)
            self._db.insert_event("ALERT", message, timestamp=_now_iso(), sector_id=sid, payload=data)

    def _handle_config_update(self, data: dict[str, Any]) -> None:
        new_cfg = data.get("settings", data)
        if not isinstance(new_cfg, dict):
            return
        thresholds = new_cfg.get("thresholds")
        if isinstance(thresholds, dict) and self._decision_engine:
            self._decision_engine.update_thresholds(thresholds)
        if "flow_rate_lpm" in new_cfg:
            try:
                self._flow_rate_lpm = float(new_cfg["flow_rate_lpm"])
            except (TypeError, ValueError):
                pass
        if "stale_data_timeout" in new_cfg:
            try:
                self._stale_data_timeout = float(new_cfg["stale_data_timeout"])
            except (TypeError, ValueError):
                pass
        if "node_offline_timeout" in new_cfg:
            try:
                self._node_offline_timeout = float(new_cfg["node_offline_timeout"])
            except (TypeError, ValueError):
                pass
        logger.info("Runtime config updated from MQTT: %s", new_cfg)
        if self._db:
            self._db.insert_event(
                "SETTINGS_UPDATE",
                "Configuration updated from dashboard",
                timestamp=_now_iso(),
                payload=new_cfg,
            )

    def _handle_control_message(self, data: dict[str, Any]) -> None:
        action = data.get("action")
        sid = data.get("sector_id")
        if action == "SET_MODE" and sid in SECTORS:
            mode = data.get("mode", "AUTO")
            self.set_mode(int(sid), str(mode))
        elif action == "EMERGENCY_OFF":
            self.emergency_all_valves_off()

    # ------------------------------------------------------------------
    # Command publishing
    # ------------------------------------------------------------------

    def _publish_command(self, sid: int, action: str, source: str = "master") -> str:
        cmd_id = str(uuid.uuid4())
        ts = _now_iso()
        payload = {
            "cmd_id": cmd_id,
            "action": action,
            "sector_id": sid,
            "timestamp": ts,
            "source": source,
        }
        topic = f"farm/sector{sid}/command"
        # NEVER retain potentially dangerous valve-OPEN commands (retain=False always)
        sent = self._mqtt.publish(topic, payload, qos=1, retain=False)

        with self._lock:
            self._sector_state[sid]["pending_cmds"][cmd_id] = {
                "action": action,
                "sent_at": _now_ts(),
            }
            self._sector_state[sid]["desired_valve_state"] = (
                "OPEN" if action == "OPEN" else "CLOSED"
            )

        if self._db:
            self._db.insert_command(cmd_id, sid, action, timestamp=ts, source=source)
            self._db.insert_event(
                "EMERGENCY" if action == "EMERGENCY_OFF" else "COMMAND",
                f"Published {action} to Sector {sid} (awaiting node ACK)",
                timestamp=ts,
                sector_id=sid,
                payload=payload,
            )

        logger.info("Published command sector=%s action=%s cmd_id=%s sent=%s", sid, action, cmd_id, sent)
        return cmd_id

    # ------------------------------------------------------------------
    # Main control loop
    # ------------------------------------------------------------------

    def _main_loop(self) -> None:
        logger.info("Main control loop started (interval=%ss).", LOOP_INTERVAL)
        while self._running:
            loop_start = _now_ts()

            self._run_decision_cycle()
            self._check_pending_ack_timeouts()
            self._publish_system_heartbeat()
            self._write_state_file(master_online=True)

            elapsed = _now_ts() - loop_start
            time.sleep(max(0.0, LOOP_INTERVAL - elapsed))
        logger.info("Main control loop exited.")

    def _publish_system_heartbeat(self) -> None:
        if not self._mqtt or not self._broker_connected:
            return
        status = self.get_system_status()
        heartbeat = {
            "master_id": "rpi5_master",
            "master_online": True,
            "broker_connected": status["broker_connected"],
            "online_node_count": status["online_node_count"],
            "active_valve_count": status["active_valve_count"],
            "total_water_consumed_litres": status["total_water_consumed_litres"],
            "timestamp": _now_iso(),
        }
        self._mqtt.publish("farm/system/status", heartbeat, qos=0, retain=False)

    def _run_decision_cycle(self) -> None:
        now = _now_ts()

        for sid in SECTORS:
            with self._lock:
                state = self._sector_state[sid]
                last_seen = state["last_seen"]
                last_fresh = state["last_fresh_ts"]
                reading = state["last_reading"]
                mode = state["mode"]
                current_valve = state["valve_state"]
                reading_valid = state["reading_valid"]
                pending_count = len(state["pending_cmds"])

            if last_seen is None:
                continue

            age = now - last_seen
            fresh_age = (now - last_fresh) if last_fresh is not None else age

            if age > self._node_offline_timeout:
                with self._lock:
                    was_online = self._sector_state[sid]["node_online"]
                    self._sector_state[sid]["node_online"] = False
                    self._sector_state[sid]["stale"] = True
                if was_online:
                    logger.warning("Sector %s node OFFLINE (last seen %.0fs ago).", sid, age)
                    self._raise_alert(
                        sid,
                        "node_offline",
                        f"Sector {sid} node OFFLINE — no telemetry for {age:.0f}s",
                        severity="CRITICAL",
                    )
                continue

            if age > self._stale_data_timeout or fresh_age > self._stale_data_timeout:
                with self._lock:
                    was_stale = self._sector_state[sid]["stale"]
                    self._sector_state[sid]["stale"] = True
                if not was_stale:
                    logger.warning("Sector %s data STALE (age=%.0fs, fresh_age=%.0fs).", sid, age, fresh_age)
                    self._raise_alert(
                        sid,
                        "stale_data",
                        f"Sector {sid} data is STALE (unchanged for {fresh_age:.0f}s); automatic decisions paused.",
                        severity="WARNING",
                    )
                continue

            if not reading_valid or reading is None:
                logger.debug("Sector %s skipping decision because reading is invalid/missing.", sid)
                continue

            if mode != "AUTO":
                continue

            try:
                decision = self._decision_engine.decide(
                    sector_id=sid,
                    sensor_reading=reading,
                    current_valve_state=current_valve,
                )
            except Exception as exc:
                logger.error("DecisionEngine error for sector %s: %s", sid, exc)
                continue

            action = decision.get("action", "MAINTAIN")
            for alert_code in decision.get("alerts", []):
                if alert_code == "high_temperature":
                    msg = f"Sector {sid} temperature {reading['temperature']:.1f}C exceeds threshold"
                    self._raise_alert(sid, "high_temperature", msg, severity="WARNING")
                elif alert_code == "low_humidity":
                    msg = f"Sector {sid} humidity {reading['humidity']:.1f}% below threshold"
                    self._raise_alert(sid, "low_humidity", msg, severity="WARNING")

            # Avoid spamming duplicate commands while waiting for an ACK
            if pending_count > 0:
                continue

            if action == "OPEN" and current_valve == "CLOSED":
                self._publish_command(sid, "OPEN")
            elif action == "CLOSE" and current_valve == "OPEN":
                self._publish_command(sid, "CLOSE")

    def _check_pending_ack_timeouts(self) -> None:
        now = _now_ts()
        if now - self._last_ack_check < ACK_CHECK_INTERVAL:
            return
        self._last_ack_check = now

        for sid in SECTORS:
            with self._lock:
                pending = dict(self._sector_state[sid]["pending_cmds"])

            for cmd_id, info in pending.items():
                elapsed = now - info["sent_at"]
                if elapsed > ACK_TIMEOUT:
                    logger.warning(
                        "Sector %s cmd_id=%s action=%s ACK TIMED OUT after %.0fs.",
                        sid,
                        cmd_id,
                        info["action"],
                        elapsed,
                    )
                    with self._lock:
                        self._sector_state[sid]["pending_cmds"].pop(cmd_id, None)
                    msg = (
                        f"Sector {sid} command {info['action']} (cmd_id={cmd_id[:8]}) "
                        f"timed out after {elapsed:.0f}s with NO acknowledgment!"
                    )
                    self._raise_alert(sid, "ack_timeout", msg, severity="CRITICAL")
                    if self._db:
                        self._db.insert_event(
                            "ACK_TIMEOUT",
                            msg,
                            timestamp=_now_iso(),
                            sector_id=sid,
                            payload={"cmd_id": cmd_id, "action": info["action"]},
                        )

    def _raise_alert(
        self,
        sid: int | None,
        alert_type: str,
        message: str,
        severity: str = "WARNING",
    ) -> None:
        now = _now_ts()
        key = (sid, alert_type)
        with self._lock:
            last_sent = self._last_alert_sent.get(key, 0.0)
            if now - last_sent < ALERT_COOLDOWN_S:
                return
            self._last_alert_sent[key] = now
            self._alert_count += 1

        payload = {
            "sector_id": sid,
            "alert_type": alert_type,
            "message": message,
            "severity": severity,
            "timestamp": _now_iso(),
            "source": "master",
        }
        if self._mqtt and self._broker_connected:
            self._mqtt.publish("farm/system/alerts", payload, qos=1, retain=False)

        logger.warning("ALERT [%s] sector=%s (%s): %s", severity, sid, alert_type, message)

        if self._db:
            self._db.insert_alert(sid, alert_type, message, timestamp=_now_iso(), severity=severity)
            self._db.insert_event("ALERT", message, timestamp=_now_iso(), sector_id=sid, payload=payload)

    def emergency_all_valves_off(self) -> None:
        logger.critical("EMERGENCY: closing ALL valves NOW.")
        threads = [
            threading.Thread(
                target=self._publish_command,
                args=(sid, "EMERGENCY_OFF", "master_emergency"),
                daemon=True,
            )
            for sid in SECTORS
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        self._raise_alert(None, "emergency_stop", "Emergency ALL VALVES OFF executed.", severity="CRITICAL")

    def set_mode(self, sid: int, mode: str) -> None:
        if sid not in SECTORS or mode not in ("AUTO", "MANUAL"):
            return
        with self._lock:
            self._sector_state[sid]["mode"] = mode
        logger.info("Sector %s mode -> %s", sid, mode)
        if self._db:
            self._db.insert_event(
                "MODE_CHANGE",
                f"Sector {sid} operating mode changed to {mode}",
                timestamp=_now_iso(),
                sector_id=sid,
                payload={"mode": mode},
            )

    def get_system_status(self, master_online: bool = True) -> dict[str, Any]:
        now = _now_ts()
        sectors_snapshot: dict[str, Any] = {}
        online_count = 0
        active_valves = 0
        total_water = 0.0

        with self._lock:
            for sid, state in self._sector_state.items():
                if state["node_online"]:
                    online_count += 1
                if state["valve_state"] == "OPEN":
                    active_valves += 1
                total_water += float(state["water_consumed_litres"])

                if not state["node_online"]:
                    conn_status = "offline"
                elif state["stale"] or not state["reading_valid"]:
                    conn_status = "stale"
                else:
                    conn_status = "online"

                decision = (
                    self._decision_engine.explain_last_decision(sid)
                    if self._decision_engine
                    else None
                )
                decision_out = dict(decision) if decision else {
                    "action": "WAIT",
                    "reason": "Waiting for valid telemetry.",
                    "explanation": "Waiting for valid telemetry.",
                    "engine_type": "rule-based engine",
                    "alerts": [],
                }
                decision_out.setdefault("explanation", decision_out.get("reason", ""))

                sectors_snapshot[str(sid)] = {
                    "sensor": state["last_reading"] or {},
                    "valve": {
                        "state": state["valve_state"],
                        "desired_state": state["desired_valve_state"],
                        "flow_rate_lpm": round(float(state["flow_rate_lpm"]), 2),
                        "water_consumed_litres": round(float(state["water_consumed_litres"]), 3),
                    },
                    "node": {
                        "status": conn_status,
                        "node_online": state["node_online"],
                        "stale": state["stale"],
                        "reading_valid": state["reading_valid"],
                        "invalid_reason": state["invalid_reason"],
                        "last_seen_ago": (
                            round(now - state["last_seen"], 1)
                            if state["last_seen"] is not None
                            else None
                        ),
                    },
                    "last_decision": decision_out,
                    "mode": state["mode"],
                    "pending_cmds_count": len(state["pending_cmds"]),
                }

            alert_count = self._alert_count
            broker_connected = self._broker_connected

        # Include active simulated faults from sim_control.json if present
        active_faults: list[dict[str, Any]] = []
        try:
            with open(SIM_CONTROL_PATH, "r", encoding="utf-8") as fh:
                sim_ctrl = json.load(fh)
            for sid_str, sc in sim_ctrl.get("sectors", {}).items():
                if sc.get("disconnect"):
                    active_faults.append({"sector_id": sid_str, "fault_type": "disconnect", "since": sc.get("updated_at", "")})
                elif sc.get("fault") and sc.get("fault") != "restore":
                    active_faults.append({"sector_id": sid_str, "fault_type": sc.get("fault"), "since": sc.get("updated_at", "")})
        except Exception:
            pass

        return {
            "master_online": master_online,
            "broker_connected": broker_connected,
            "online_node_count": online_count,
            "active_valve_count": active_valves,
            "total_water_consumed_litres": round(total_water, 3),
            "alert_count": alert_count,
            "timestamp": _now_iso(),
            "thresholds": self._decision_engine.thresholds if self._decision_engine else {},
            "flow_rate_lpm": self._flow_rate_lpm,
            "active_faults": active_faults,
            "sectors": sectors_snapshot,
        }

    def _write_state_file(self, master_online: bool = True) -> None:
        status = self.get_system_status(master_online=master_online)
        tmp_path = STATE_FILE + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(status, fh, indent=2, default=str)
            os.replace(tmp_path, STATE_FILE)
        except OSError as exc:
            logger.error("Failed to write state file: %s", exc)


def main() -> None:
    master = RaspberryPiMaster()
    master.start()
    try:
        while master._running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        master.shutdown()


if __name__ == "__main__":
    main()
