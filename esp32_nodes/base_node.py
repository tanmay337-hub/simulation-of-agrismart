"""
base_node.py — Shared virtual ESP32 node runtime.

Simulates an ESP32 microcontroller connected to soil-moisture, temperature,
humidity, and light sensors plus a solenoid irrigation valve.

HARDWARE REPLACEMENT GUIDE:
  - SensorSimulator  -> ADC / I2C / DHT22 hardware sensor drivers on GPIO pins.
  - IrrigationModel  -> GPIO relay output + YF-S201 Hall-effect water flow meter.
  - data/sim_control.json -> Removed entirely on physical ESP32 hardware.
  - Paho-MQTT on PC  -> Wi-Fi + PubSubClient / esp_mqtt on the ESP32.
"""

import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

# Ensure project root is importable when invoked directly.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import paho.mqtt.client as mqtt
from simulation.irrigation_model import IrrigationModel
from simulation.sensor_simulator import SensorSimulator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_safe(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _create_mqtt_client(client_id: str) -> mqtt.Client:
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
    return mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)


def run_esp32_node(sector_id: int) -> None:
    """Run an independent virtual ESP32 process for the given farm sector."""
    node_id = f"esp32_sector_{sector_id}"
    config_path = os.path.join(_PROJECT_ROOT, "config", "settings.json")
    sim_control_path = os.path.join(_PROJECT_ROOT, "data", "sim_control.json")

    config = _load_json_safe(config_path)
    mqtt_cfg = config.get("mqtt", {})
    broker = mqtt_cfg.get("broker", "localhost")
    port = int(mqtt_cfg.get("port", 1883))
    keepalive = int(mqtt_cfg.get("keepalive", 60))

    publish_interval = float(config.get("sensor_publish_interval", 5))
    failsafe_timeout = float(config.get("failsafe_timeout", 90))
    flow_rate_lpm = float(config.get("flow_rate_lpm", 2.0))

    log_cfg = config.get("logging", {})
    log_level = getattr(logging, str(log_cfg.get("level", "INFO")).upper(), logging.INFO)
    log_file = os.path.join(_PROJECT_ROOT, "logs", f"esp32_sector_{sector_id}.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger(node_id)
    logger.setLevel(log_level)
    logger.handlers.clear()
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(ch)
    logger.addHandler(fh)

    # MQTT Topics (strictly scoped to this sector's command/sensors/status)
    topic_sensors = f"farm/sector{sector_id}/sensors"
    topic_command = f"farm/sector{sector_id}/command"
    topic_status = f"farm/sector{sector_id}/status"
    topic_alerts = "farm/system/alerts"
    topic_system_status = "farm/system/status"
    topic_system_config = "farm/system/config"

    # Simulated hardware peripherals
    irrigation = IrrigationModel(flow_rate_lpm=flow_rate_lpm, sector_ids=[sector_id])
    sensor_sim = SensorSimulator(config_path=config_path, irrigation_model=irrigation)

    lock = threading.Lock()
    state: dict[str, Any] = {
        "last_master_contact": time.monotonic(),
        "shutdown": False,
        "mqtt_connected": False,
        "simulated_disconnect": False,
        "last_fault_nonce": None,
        "last_override_nonce": None,
        "delay_seconds": 0.0,
        "failsafe_timeout": failsafe_timeout,
        "publish_interval": publish_interval,
    }

    client_id = f"{node_id}_{uuid.uuid4().hex[:8]}"
    mqtt_client = _create_mqtt_client(client_id)

    def publish_json(topic: str, payload: dict[str, Any], qos: int = 1, retain: bool = False) -> None:
        with lock:
            connected = state["mqtt_connected"]
            sim_disc = state["simulated_disconnect"]
        if not connected or sim_disc:
            logger.debug("Skipping publish to %s (connected=%s, sim_disconnect=%s)", topic, connected, sim_disc)
            return
        try:
            mqtt_client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        except Exception as exc:
            logger.error("Publish error on %s: %s", topic, exc)

    def publish_status(cmd_id: str, status: str, reason: str = "") -> None:
        valve_info = irrigation.get_status(sector_id)
        payload = {
            "cmd_id": cmd_id,
            "sector_id": sector_id,
            "node_id": node_id,
            "status": status,
            "valve_state": valve_info["valve_state"],
            "flow_rate_lpm": valve_info["flow_rate_lpm"],
            "water_consumed_litres": valve_info["water_consumed_litres"],
            "timestamp": _now_iso(),
            "reason": reason,
        }
        publish_json(topic_status, payload, qos=1, retain=False)
        logger.info(
            "Status published: cmd_id=%s status=%s valve=%s reason=%s",
            cmd_id,
            status,
            valve_info["valve_state"],
            reason,
        )

    def publish_alert(alert_type: str, message: str, severity: str = "CRITICAL") -> None:
        payload = {
            "sector_id": sector_id,
            "node_id": node_id,
            "alert_type": alert_type,
            "message": message,
            "severity": severity,
            "timestamp": _now_iso(),
        }
        publish_json(topic_alerts, payload, qos=1, retain=False)
        logger.warning("ALERT published: type=%s msg=%s", alert_type, message)

    def on_connect(client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
        if rc == 0:
            with lock:
                state["mqtt_connected"] = True
            logger.info("Connected to MQTT broker %s:%s", broker, port)
            # Subscribe ONLY to this node's command topic + system heartbeat/config.
            client.subscribe(topic_command, qos=1)
            client.subscribe(topic_system_status, qos=0)
            client.subscribe(topic_system_config, qos=1)
            logger.info("Subscribed to %s (+ system heartbeat/config)", topic_command)
            publish_status("boot", "ONLINE", "Node connected")
        else:
            with lock:
                state["mqtt_connected"] = False
            logger.error("MQTT connect failed with rc=%d", rc)

    def on_disconnect(client: mqtt.Client, userdata: Any, rc: int) -> None:
        with lock:
            state["mqtt_connected"] = False
        if rc != 0:
            logger.warning("Unexpected MQTT disconnect (rc=%d).", rc)

    def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        topic = msg.topic
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if topic == topic_command:
                logger.warning("Malformed command JSON: %s — %s", msg.payload, exc)
                publish_status("unknown", "REJECTED", f"Malformed JSON: {exc}")
            return

        if topic == topic_system_status:
            # Master heartbeat received — keep fail-safe watchdog alive
            if data.get("master_online", True):
                with lock:
                    state["last_master_contact"] = time.monotonic()
            return

        if topic == topic_system_config:
            new_cfg = data.get("settings", data)
            if isinstance(new_cfg, dict):
                if "flow_rate_lpm" in new_cfg:
                    try:
                        new_flow = float(new_cfg["flow_rate_lpm"])
                        irrigation.set_flow_rate(sector_id, new_flow)
                    except (TypeError, ValueError):
                        pass
                if "failsafe_timeout" in new_cfg:
                    try:
                        with lock:
                            state["failsafe_timeout"] = float(new_cfg["failsafe_timeout"])
                    except (TypeError, ValueError):
                        pass
            return

        if topic != topic_command:
            return

        # Command from master (or dashboard): update master-contact timer if from master
        if data.get("source") == "master":
            with lock:
                state["last_master_contact"] = time.monotonic()

        logger.info("Command received: %s", data)

        # Enforce sector isolation if sector_id is provided in payload
        target_sector = data.get("sector_id")
        if target_sector is not None and str(target_sector) != str(sector_id):
            reason = f"Sector isolation violation: command for sector {target_sector} rejected by sector {sector_id}"
            logger.error(reason)
            publish_status(str(data.get("cmd_id") or "unknown"), "REJECTED", reason)
            return

        cmd_id = data.get("cmd_id")
        action = data.get("action")
        timestamp = data.get("timestamp")

        if not cmd_id or not action or not timestamp:
            reason = "Missing required fields: cmd_id, action, or timestamp"
            logger.warning("Rejecting command: %s", reason)
            publish_status(str(cmd_id or "unknown"), "REJECTED", reason)
            return

        if action not in ("OPEN", "CLOSE", "EMERGENCY_OFF"):
            reason = f"Unknown action '{action}'. Must be OPEN, CLOSE, or EMERGENCY_OFF."
            logger.warning("Rejecting command: %s", reason)
            publish_status(str(cmd_id), "REJECTED", reason)
            return

        prev_state = irrigation.get_status(sector_id)["valve_state"]

        if action == "OPEN":
            ok = irrigation.open_valve(sector_id)
        else:
            # EMERGENCY_OFF overrides normal close; if faulted, simulate unresponsive valve
            ok = irrigation.close_valve(sector_id)

        if not ok:
            # Simulated valve fault: hardware fails to actuate and fails to confirm ACK
            logger.error(
                "VALVE FAULT: Sector %d valve failed to respond to %s (cmd_id=%s). No ACK sent.",
                sector_id,
                action,
                cmd_id,
            )
            return

        new_state = irrigation.get_status(sector_id)["valve_state"]
        logger.info("Valve state: %s -> %s (action=%s cmd_id=%s)", prev_state, new_state, action, cmd_id)
        publish_status(str(cmd_id), "ACCEPTED", f"Action {action} executed successfully")

    def poll_sim_control() -> None:
        """
        SIMULATION HARNESS ONLY: reads data/sim_control.json written by the
        dashboard so cross-process fault injection and manual sensor adjustments
        work even when a node is MQTT-disconnected.
        """
        ctrl = _load_json_safe(sim_control_path)
        # 0. Global crisis mode (heatwave, rainstorm, frost, water_supply_failure, broker_outage)
        crisis = ctrl.get("crisis", "normal")
        sensor_sim.set_crisis_mode(crisis)
        irrigation.set_water_supply_failed(crisis == "water_supply_failure")
        with lock:
            state["crisis"] = crisis

        sec_ctrl = ctrl.get("sectors", {}).get(str(sector_id), {})
        if not sec_ctrl:
            return

        # 1. Disconnect / Reconnect control (also disconnects during broker_outage crisis)
        want_disconnect = bool(sec_ctrl.get("disconnect", False)) or crisis == "broker_outage"
        with lock:
            cur_disc = state["simulated_disconnect"]
            if want_disconnect != cur_disc:
                state["simulated_disconnect"] = want_disconnect
                if want_disconnect:
                    logger.warning("SIM FAULT: Node disconnect triggered — disconnecting MQTT.")
                    try:
                        mqtt_client.disconnect()
                    except Exception:
                        pass
                else:
                    logger.info("SIM RECOVERY: Node reconnect triggered.")

        # 1b. Per-sensor faults (moisture, temperature, humidity, light_lux, flow)
        s_faults = sec_ctrl.get("sensor_faults", {})
        if isinstance(s_faults, dict):
            for s_name in ("moisture", "temperature", "humidity", "light_lux"):
                mode = s_faults.get(s_name, "ok")
                if sensor_sim.get_sensor_faults(sector_id).get(s_name) != mode:
                    sensor_sim.set_sensor_fault(sector_id, s_name, mode)
            with lock:
                state["flow_sensor_fault"] = s_faults.get("flow", "ok")

        # 1c. Granular valve fault mode (normal, stuck_closed, stuck_open, no_ack, leak)
        v_fault_mode = sec_ctrl.get("valve_fault_mode", "normal")
        if irrigation.get_status(sector_id).get("fault_mode") != v_fault_mode:
            irrigation.set_valve_fault_mode(sector_id, v_fault_mode)
            logger.warning("SIM VALVE FAULT MODE set to '%s' on sector %d.", v_fault_mode, sector_id)

        # 2. Fault injection (keyed by fault_nonce)
        fault_nonce = sec_ctrl.get("fault_nonce")
        with lock:
            prev_nonce = state["last_fault_nonce"]
        if fault_nonce is not None and fault_nonce != prev_nonce:
            with lock:
                state["last_fault_nonce"] = fault_nonce
            fault_type = sec_ctrl.get("fault")
            if fault_type is None or fault_type == "restore":
                sensor_sim.clear_fault(sector_id)
                irrigation.clear_valve_fault(sector_id)
                with lock:
                    state["delay_seconds"] = 0.0
                logger.info("SIM RECOVERY: All simulated faults cleared for sector %d.", sector_id)
            elif fault_type == "stale":
                sensor_sim.inject_fault(sector_id, "stale", duration_s=float(sec_ctrl.get("duration_s", 45.0)))
            elif fault_type == "invalid":
                sensor_sim.inject_fault(sector_id, "invalid")
            elif fault_type == "missing":
                sensor_sim.inject_fault(sector_id, "missing")
            elif fault_type == "noise_spike":
                sensor_sim.inject_fault(sector_id, "noise_spike")
            elif fault_type == "delay":
                delay_s = float(sec_ctrl.get("delay_s", 10.0))
                with lock:
                    state["delay_seconds"] = delay_s
                logger.warning("SIM FAULT: Publish delay set to %.1fs for sector %d.", delay_s, sector_id)
            elif fault_type == "valve_fault":
                irrigation.simulate_valve_fault(sector_id, duration_s=float(sec_ctrl.get("duration_s", 35.0)))

        # 3. Manual sensor value override from dashboard
        override = sec_ctrl.get("manual_override")
        if isinstance(override, dict):
            ov_nonce = override.get("nonce")
            with lock:
                prev_ov = state["last_override_nonce"]
            if ov_nonce is not None and ov_nonce != prev_ov:
                with lock:
                    state["last_override_nonce"] = ov_nonce
                for field in ("moisture", "temperature", "humidity", "light_lux"):
                    if field in override and override[field] is not None:
                        sensor_sim.set_manual_value(sector_id, field, float(override[field]))
                logger.info("SIM OVERRIDE: Manual sensor override applied: %s", override)

    def connect_with_backoff() -> None:
        delay = 1.0
        max_delay = 60.0
        while not state["shutdown"]:
            with lock:
                if state["simulated_disconnect"]:
                    time.sleep(1.0)
                    continue
            try:
                logger.info("Attempting MQTT connection to %s:%s ...", broker, port)
                mqtt_client.connect(broker, port, keepalive=keepalive)
                return
            except Exception as exc:
                logger.error("MQTT connection failed: %s. Retrying in %.0fs ...", exc, delay)
                time.sleep(delay)
                delay = min(delay * 2.0, max_delay)

    def sensor_publish_loop() -> None:
        logger.info("Sensor publish loop started (interval=%.1fs)", publish_interval)
        first_tick = True
        while not state["shutdown"]:
            loop_start = time.monotonic()
            poll_sim_control()

            with lock:
                sim_disc = state["simulated_disconnect"]
                delay_s = state["delay_seconds"]
                interval = state["publish_interval"]

            if not sim_disc:
                try:
                    if not first_tick:
                        sensor_sim.update(sector_id)
                        irrigation.tick(interval)
                    first_tick = False

                    reading = sensor_sim.get_reading(sector_id)
                    valve_status = irrigation.get_status(sector_id)

                    if reading is None:
                        logger.warning("SIM FAULT: Missing reading for sector %d — skipping telemetry publish.", sector_id)
                    else:
                        if delay_s > 0:
                            logger.warning("SIM FAULT: Delaying telemetry publish by %.1fs ...", delay_s)
                            time.sleep(delay_s)
                            with lock:
                                state["delay_seconds"] = 0.0

                        def _r(val, digits=2):
                            return round(float(val), digits) if isinstance(val, (int, float)) else None

                        with lock:
                            flow_fault = state.get("flow_sensor_fault", "ok")
                            cur_crisis = state.get("crisis", "normal")

                        eff_flow = float(valve_status.get("effective_flow_lpm", 0.0))
                        if flow_fault == "missing":
                            eff_flow_out = None
                        elif flow_fault == "invalid":
                            eff_flow_out = -9.9
                        elif flow_fault == "stale":
                            eff_flow_out = state.setdefault("frozen_flow", eff_flow)
                        elif flow_fault == "noisy":
                            eff_flow_out = round(eff_flow + 4.5, 2)
                        else:
                            state.pop("frozen_flow", None)
                            eff_flow_out = round(eff_flow, 2)

                        sensor_health = sensor_sim.get_sensor_faults(sector_id)
                        sensor_health["flow"] = flow_fault

                        payload = {
                            "node_id": node_id,
                            "sector_id": sector_id,
                            "moisture": _r(reading["moisture"], 2),
                            "temperature": _r(reading["temperature"], 2),
                            "humidity": _r(reading["humidity"], 2),
                            "light_lux": _r(reading["light_lux"], 1),
                            "timestamp": reading["timestamp"],
                            "sequence_number": reading["sequence_number"],
                            "valve_state": valve_status["valve_state"],
                            "valve_fault_mode": valve_status.get("fault_mode", "normal"),
                            "flow_rate_lpm": eff_flow_out,
                            "nominal_flow_rate_lpm": valve_status["flow_rate_lpm"],
                            "water_consumed_litres": valve_status["water_consumed_litres"],
                            "sensor_health": sensor_health,
                            "crisis": cur_crisis,
                        }
                        publish_json(topic_sensors, payload, qos=1, retain=False)
                        logger.info(
                            "Telemetry seq=%s m=%s t=%s h=%s valve=%s flow=%s water=%.2fL",
                            payload["sequence_number"],
                            payload["moisture"],
                            payload["temperature"],
                            payload["humidity"],
                            payload["valve_state"],
                            payload["flow_rate_lpm"],
                            payload["water_consumed_litres"],
                        )
                except Exception as exc:
                    logger.exception("Error in sensor publish loop: %s", exc)
            else:
                logger.debug("Node simulated offline — skipping telemetry publish.")

            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.2, interval - elapsed))

    def failsafe_watchdog() -> None:
        logger.info("Fail-safe watchdog started (timeout=%.0fs)", failsafe_timeout)
        while not state["shutdown"]:
            time.sleep(2.0)
            with lock:
                since_contact = time.monotonic() - state["last_master_contact"]
                timeout = state["failsafe_timeout"]
            if since_contact > timeout:
                current_state = irrigation.get_status(sector_id)["valve_state"]
                if current_state == "OPEN":
                    logger.critical(
                        "FAIL-SAFE TRIGGERED: No master contact for %.0fs (> %.0fs). Auto-closing valve!",
                        since_contact,
                        timeout,
                    )
                    irrigation.clear_valve_fault(sector_id)
                    irrigation.close_valve(sector_id)
                    publish_alert(
                        "failsafe_triggered",
                        f"No master heartbeat/command for {since_contact:.0f}s. Valve auto-closed on {node_id}.",
                        severity="CRITICAL",
                    )
                    publish_status("failsafe", "ACCEPTED", "Local fail-safe closed valve after timeout")
                    with lock:
                        state["last_master_contact"] = time.monotonic()

    def graceful_shutdown(signum: int | None = None, frame: Any = None) -> None:
        with lock:
            if state["shutdown"]:
                return
            state["shutdown"] = True
        logger.info("Shutdown signal received. Closing valve and disconnecting ...")
        try:
            irrigation.clear_valve_fault(sector_id)
            irrigation.close_valve(sector_id)
            publish_status("shutdown", "OFFLINE", "Node shutting down; valve closed")
            time.sleep(0.3)
        except Exception as exc:
            logger.error("Error closing valve on shutdown: %s", exc)
        try:
            mqtt_client.disconnect()
        except Exception:
            pass

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    logger.info("=" * 60)
    logger.info("Starting %s — Sector %d Virtual ESP32 Node", node_id, sector_id)
    logger.info("=" * 60)

    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    connect_with_backoff()
    mqtt_client.loop_start()

    with lock:
        state["last_master_contact"] = time.monotonic()

    t_pub = threading.Thread(target=sensor_publish_loop, daemon=True, name=f"pub-s{sector_id}")
    t_wd = threading.Thread(target=failsafe_watchdog, daemon=True, name=f"wd-s{sector_id}")
    t_pub.start()
    t_wd.start()

    try:
        while not state["shutdown"]:
            poll_sim_control()
            with lock:
                connected = state["mqtt_connected"]
                sim_disc = state["simulated_disconnect"]
                shutdown = state["shutdown"]
            if not connected and not sim_disc and not shutdown:
                logger.info("Reconnecting to MQTT broker ...")
                try:
                    mqtt_client.reconnect()
                except Exception:
                    connect_with_backoff()
            time.sleep(2.0)
    except KeyboardInterrupt:
        graceful_shutdown()
    finally:
        mqtt_client.loop_stop()
        logger.info("%s stopped.", node_id)
