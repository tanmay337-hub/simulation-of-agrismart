"""
Smart Agriculture Irrigation System - Streamlit Dashboard
Reads live state from data/system_state.json and history from data/farm_history.db.
Publishes commands/config/control via MQTT (paho-mqtt) and writes cross-process
simulation fault controls to data/sim_control.json (simulation harness only).
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

import pandas as pd
import paho.mqtt.client as mqtt
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "system_state.json"
DB_FILE = PROJECT_ROOT / "data" / "farm_history.db"
CFG_FILE = PROJECT_ROOT / "config" / "settings.json"
SIM_CTRL_FILE = PROJECT_ROOT / "data" / "sim_control.json"
MASTER_SCRIPT = PROJECT_ROOT / "master" / "raspberry_pi_master.py"

SECTORS = [1, 2, 3, 4]

st.set_page_config(
    page_title="Smart Farm Dashboard",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .status-green  { color: #2ecc71; font-weight: bold; }
    .status-red    { color: #e74c3c; font-weight: bold; }
    .status-amber  { color: #f39c12; font-weight: bold; }
    .card          { background:#1e1e2e; border-radius:12px; padding:16px; margin-bottom:12px; }
    .emergency-btn button { background-color:#e74c3c !important; color:white !important; font-size:1.05rem !important; font-weight:bold !important; }
    div[data-testid="stMetricValue"] { font-size: 1.3rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ═════════════════════════════════════════════════════════════════════════════
# THREAD-SAFE MQTT CLIENT (never touches st.session_state from paho thread)
# ═════════════════════════════════════════════════════════════════════════════


class MQTTStateHolder:
    """Thread-safe container for dashboard MQTT client and live alerts."""

    def __init__(self, broker: str = "localhost", port: int = 1883) -> None:
        self.lock = threading.Lock()
        self.connected = False
        self.error = ""
        self.live_alerts: list[dict] = []
        self.broker = broker
        self.port = port

        if hasattr(mqtt, "CallbackAPIVersion"):
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id=f"dashboard-{uuid.uuid4().hex[:6]}",
                protocol=mqtt.MQTTv311,
            )
        else:
            self.client = mqtt.Client(
                client_id=f"dashboard-{uuid.uuid4().hex[:6]}",
                protocol=mqtt.MQTTv311,
            )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._connect()

    def _connect(self) -> None:
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
        except Exception as exc:
            with self.lock:
                self.connected = False
                self.error = str(exc)

    def _on_connect(self, client, userdata, flags, rc) -> None:
        with self.lock:
            self.connected = rc == 0
            if rc == 0:
                self.error = ""
        if rc == 0:
            client.subscribe("farm/system/alerts", qos=1)

    def _on_disconnect(self, client, userdata, rc) -> None:
        with self.lock:
            self.connected = False

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            payload = {"message": msg.payload.decode("utf-8", errors="replace")}
        with self.lock:
            self.live_alerts.append({
                "topic": msg.topic,
                "payload": payload,
                "time": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
            })
            self.live_alerts = self.live_alerts[-50:]

    def reconnect_if_needed(self) -> None:
        with self.lock:
            is_conn = self.connected
        if not is_conn:
            try:
                self.client.reconnect()
            except Exception:
                self._connect()

    def snapshot(self) -> tuple[bool, str, list[dict]]:
        with self.lock:
            return self.connected, self.error, list(self.live_alerts)

    def publish(self, topic: str, payload: dict, qos: int = 1) -> bool:
        try:
            res = self.client.publish(topic, json.dumps(payload), qos=qos, retain=False)
            return res.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
            return False


@st.cache_resource
def get_mqtt_holder() -> MQTTStateHolder:
    cfg = load_settings()
    mqtt_cfg = cfg.get("mqtt", {})
    return MQTTStateHolder(
        broker=mqtt_cfg.get("broker", "localhost"),
        port=int(mqtt_cfg.get("port", 1883)),
    )


def publish_valve_command(sector_id: int, action: str) -> None:
    payload = {
        "cmd_id": str(uuid.uuid4()),
        "action": action,
        "sector_id": sector_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "dashboard",
    }
    get_mqtt_holder().publish(f"farm/sector{sector_id}/command", payload, qos=1)


def publish_mode_change(sector_id: int, mode: str) -> None:
    payload = {
        "cmd_id": str(uuid.uuid4()),
        "action": "SET_MODE",
        "sector_id": sector_id,
        "mode": mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "dashboard",
    }
    get_mqtt_holder().publish("farm/system/control", payload, qos=1)


def publish_emergency_off() -> None:
    holder = get_mqtt_holder()
    for sid in SECTORS:
        payload = {
            "cmd_id": str(uuid.uuid4()),
            "action": "EMERGENCY_OFF",
            "sector_id": sid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "dashboard_emergency",
        }
        holder.publish(f"farm/sector{sid}/command", payload, qos=1)


def publish_settings(settings: dict) -> None:
    payload = {
        "cmd_id": str(uuid.uuid4()),
        "settings": settings,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "dashboard",
    }
    get_mqtt_holder().publish("farm/system/config", payload, qos=1)


# ═════════════════════════════════════════════════════════════════════════════
# SIMULATION CONTROL FILE HELPERS (cross-process fault & manual sensor overrides)
# ═════════════════════════════════════════════════════════════════════════════


def _load_sim_control() -> dict:
    try:
        with open(SIM_CTRL_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"sectors": {}}


def _save_sim_control(data: dict) -> None:
    SIM_CTRL_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(SIM_CTRL_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, SIM_CTRL_FILE)


def write_sector_fault(sector_id: int, fault_type: str | None, **extra) -> None:
    ctrl = _load_sim_control()
    sec = ctrl.setdefault("sectors", {}).setdefault(str(sector_id), {})
    if fault_type == "disconnect":
        sec["disconnect"] = True
    elif fault_type == "reconnect":
        sec["disconnect"] = False
    elif fault_type == "restore":
        sec["disconnect"] = False
        sec["fault"] = "restore"
        sec["fault_nonce"] = str(uuid.uuid4())
    else:
        sec["fault"] = fault_type
        sec["fault_nonce"] = str(uuid.uuid4())
        sec.update(extra)
    sec["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_sim_control(ctrl)


def restore_all_faults() -> None:
    ctrl = _load_sim_control()
    for sid in SECTORS:
        sec = ctrl.setdefault("sectors", {}).setdefault(str(sid), {})
        sec["disconnect"] = False
        sec["fault"] = "restore"
        sec["fault_nonce"] = str(uuid.uuid4())
        sec["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_sim_control(ctrl)


def write_manual_sensor_override(
    sector_id: int, moisture: float, temperature: float, humidity: float
) -> None:
    ctrl = _load_sim_control()
    sec = ctrl.setdefault("sectors", {}).setdefault(str(sector_id), {})
    sec["manual_override"] = {
        "nonce": str(uuid.uuid4()),
        "moisture": float(moisture),
        "temperature": float(temperature),
        "humidity": float(humidity),
    }
    _save_sim_control(ctrl)


# ═════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═════════════════════════════════════════════════════════════════════════════


def load_system_state() -> dict | None:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        ts_str = state.get("timestamp")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                if age > 15:
                    state["master_online"] = False
                    state["master_stale_age_s"] = round(age, 1)
            except Exception:
                pass
        return state
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_settings() -> dict:
    try:
        with open(CFG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def db_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    try:
        conn = sqlite3.connect(DB_FILE, timeout=5)
        df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def load_sensor_history(limit: int = 240) -> pd.DataFrame:
    sql = """
        SELECT sector_id, recorded_at AS timestamp, moisture, temperature, humidity, water_consumed_litres
        FROM sensor_readings
        ORDER BY id DESC
        LIMIT ?
    """
    df = db_query(sql, (limit,))
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", errors="coerce")
    return df.dropna(subset=["timestamp"]).sort_values("timestamp")


def load_event_log(sector_filter: str = "All", type_filter: str = "All") -> pd.DataFrame:
    conditions = []
    params: list = []

    if sector_filter != "All":
        sid = sector_filter.replace("Sector ", "").strip()
        conditions.append("sector_id = ?")
        params.append(sid)

    if type_filter != "All":
        conditions.append("event_type = ?")
        params.append(type_filter)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT created_at AS timestamp, sector_id, event_type, description, payload
        FROM events
        {where}
        ORDER BY id DESC
        LIMIT 200
    """
    df = db_query(sql, tuple(params))
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", errors="coerce")
    return df


def load_command_ack_history() -> pd.DataFrame:
    sql = """
        SELECT c.issued_at, c.sector_id, c.action, c.source,
               CASE WHEN c.acked = 1 THEN 'ACKED' ELSE 'PENDING / TIMEOUT' END AS delivery_status,
               a.status AS node_ack_status, a.valve_state, a.reason, a.acked_at
        FROM commands c
        LEFT JOIN acknowledgments a ON a.cmd_id = c.cmd_id
        ORDER BY c.id DESC
        LIMIT 50
    """
    return db_query(sql)


def load_current_alerts() -> pd.DataFrame:
    sql = """
        SELECT created_at AS timestamp, sector_id, alert_type, message, severity
        FROM alerts
        WHERE resolved = 0
        ORDER BY id DESC
        LIMIT 50
    """
    return db_query(sql)


# ═════════════════════════════════════════════════════════════════════════════
# HELPER RENDERERS
# ═════════════════════════════════════════════════════════════════════════════


def _connectivity_badge(status: str) -> str:
    if status == "online":
        return '<span class="status-green">● ONLINE</span>'
    if status == "stale":
        return '<span class="status-amber">● STALE / INVALID</span>'
    return '<span class="status-red">● OFFLINE</span>'


def _valve_badge(state: str) -> str:
    if state == "OPEN":
        return '<span class="status-green">🟢 OPEN</span>'
    return '<span class="status-red">🔴 CLOSED</span>'


def _mode_badge(mode: str) -> str:
    if mode == "AUTO":
        return '<span class="status-green">AUTO</span>'
    return '<span class="status-amber">MANUAL OVERRIDE</span>'


def render_sector_card(col, sector_id: int, state: dict) -> None:
    s_data = state.get("sectors", {}).get(str(sector_id), {})
    if not s_data:
        col.warning(f"Sector {sector_id}: Waiting for telemetry...")
        return

    sensor = s_data.get("sensor", {})
    valve = s_data.get("valve", {})
    node = s_data.get("node", {})
    decision = s_data.get("last_decision", {})
    mode = s_data.get("mode", "AUTO")
    pending_cnt = int(s_data.get("pending_cmds_count", 0))

    with col:
        st.markdown(f"### 🌾 Sector {sector_id}")
        last_ago = node.get("last_seen_ago")
        ago_txt = f"({last_ago}s ago)" if last_ago is not None else "(no telemetry yet)"
        st.markdown(
            f"{_connectivity_badge(node.get('status', 'offline'))} {ago_txt} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Mode: {_mode_badge(mode)}",
            unsafe_allow_html=True,
        )

        if node.get("invalid_reason"):
            st.error(f"Invalid telemetry rejected: {node['invalid_reason']}")

        c1, c2 = st.columns(2)
        moisture = float(sensor.get("moisture", 0.0))
        temp = float(sensor.get("temperature", 0.0))
        humidity = float(sensor.get("humidity", 0.0))
        lux = float(sensor.get("light_lux", 0.0))

        prev_m = st.session_state.get(f"prev_moisture_{sector_id}", moisture)
        prev_t = st.session_state.get(f"prev_temp_{sector_id}", temp)

        c1.metric("💧 Soil Moisture", f"{moisture:.1f} %", delta=f"{moisture - prev_m:+.1f}")
        c2.metric("🌡️ Temperature", f"{temp:.1f} °C", delta=f"{temp - prev_t:+.1f}")
        c1.metric("💨 Humidity", f"{humidity:.1f} %")
        c2.metric("☀️ Light", f"{lux:.0f} lux")

        st.session_state[f"prev_moisture_{sector_id}"] = moisture
        st.session_state[f"prev_temp_{sector_id}"] = temp

        valve_state = valve.get("state", "CLOSED")
        desired_state = valve.get("desired_state", valve_state)
        flow_lpm = float(valve.get("flow_rate_lpm", 0.0))
        active_flow = flow_lpm if valve_state == "OPEN" else 0.0
        consumed = float(valve.get("water_consumed_litres", 0.0))

        pending_html = (
            f" &nbsp; <span class='status-amber'>(Awaiting ACK for {desired_state})</span>"
            if pending_cnt > 0
            else ""
        )
        st.markdown(
            f"**Confirmed Valve:** {_valve_badge(valve_state)}{pending_html} &nbsp;|&nbsp; "
            f"**Flow:** {active_flow:.1f} L/min &nbsp;|&nbsp; "
            f"**Used:** {consumed:.2f} L",
            unsafe_allow_html=True,
        )

        reason = decision.get("reason") or decision.get("explanation") or "No decision recorded yet."
        engine_label = decision.get("engine_type", "rule-based engine")
        with st.expander(f"🤖 Decision Explanation ({engine_label})", expanded=True):
            st.caption(f"**Action:** `{decision.get('action', 'WAIT')}` — {reason}")

        new_mode = st.radio(
            f"Sector {sector_id} Operating Mode",
            options=["AUTO", "MANUAL"],
            index=0 if mode == "AUTO" else 1,
            horizontal=True,
            key=f"mode_radio_{sector_id}",
        )
        if new_mode != mode:
            publish_mode_change(sector_id, new_mode)
            st.toast(f"Sector {sector_id} switched to {new_mode} mode")

        if new_mode == "MANUAL":
            st.warning(f"Sector {sector_id}: Manual command mode active — automatic rules paused.")
            bc1, bc2 = st.columns(2)
            if bc1.button(f"🟢 OPEN Sector {sector_id} Valve", key=f"open_{sector_id}", width='stretch'):
                publish_valve_command(sector_id, "OPEN")
                st.success(f"Sector {sector_id}: OPEN command published (awaiting node ACK)")
            if bc2.button(f"🔴 CLOSE Sector {sector_id} Valve", key=f"close_{sector_id}", width='stretch'):
                publish_valve_command(sector_id, "CLOSE")
                st.info(f"Sector {sector_id}: CLOSE command published (awaiting node ACK)")

        with st.expander(f"🎛️ Adjust Sector {sector_id} Sensor Values"):
            sc1, sc2, sc3 = st.columns(3)
            ov_m = sc1.number_input("Moisture %", 0.0, 100.0, value=round(moisture, 1), step=1.0, key=f"ov_m_{sector_id}")
            ov_t = sc2.number_input("Temp °C", -5.0, 55.0, value=round(temp, 1), step=0.5, key=f"ov_t_{sector_id}")
            ov_h = sc3.number_input("Humidity %", 0.0, 100.0, value=round(humidity, 1), step=1.0, key=f"ov_h_{sector_id}")
            if st.button(f"Apply to Sector {sector_id}", key=f"apply_ov_{sector_id}"):
                write_manual_sensor_override(sector_id, ov_m, ov_t, ov_h)
                st.success(f"Sector {sector_id} sensor override queued!")

        st.divider()


# ═════════════════════════════════════════════════════════════════════════════
# PAGES
# ═════════════════════════════════════════════════════════════════════════════


def page_overview(state: dict | None, mqtt_ok: bool, mqtt_err: str, live_alerts: list[dict]) -> None:
    st.title("🌱 Farm-Wide Irrigation Overview")

    if state is None:
        st.warning("⏳ Waiting for Master Controller (`data/system_state.json` not created yet)...")
        return

    master_ok = state.get("master_online", False)
    broker_ok = state.get("broker_connected", False)
    online_nodes = state.get("online_node_count", 0)
    total_water = state.get("total_water_consumed_litres", 0.0)
    active_valves = state.get("active_valve_count", 0)
    last_update = state.get("timestamp", "unknown")

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Master Process", "🟢 ONLINE" if master_ok else "🔴 OFFLINE")
    k2.metric("Master MQTT", "🟢 Connected" if broker_ok else "🔴 Disconnected")
    k3.metric("Online Nodes", f"{online_nodes} / 4")
    k4.metric("Total Water Used", f"{total_water:.2f} L")
    k5.metric("Active Valves", f"{active_valves} / 4")

    if not master_ok and state.get("master_stale_age_s"):
        st.error(f"Master Controller appears STOPPED or frozen (last update {state['master_stale_age_s']}s ago).")
    st.caption(f"Last master snapshot: {last_update} | Decision engine: Rule-based ('fake AI', deterministic thresholds)")

    if mqtt_ok:
        st.success("Dashboard MQTT: Connected to broker")
    else:
        st.error(f"Dashboard MQTT: Disconnected{' — ' + mqtt_err if mqtt_err else ''}")

    st.divider()

    # Quick 4-sector status strip
    st.markdown("### 🌾 Sector Quick Status")
    scols = st.columns(4)
    for idx, sid in enumerate(SECTORS):
        s_data = state.get("sectors", {}).get(str(sid), {})
        sensor = s_data.get("sensor", {})
        valve = s_data.get("valve", {})
        node = s_data.get("node", {})
        mode = s_data.get("mode", "AUTO")
        with scols[idx]:
            st.markdown(f"**Sector {sid}** ({mode})")
            st.markdown(
                f"{_connectivity_badge(node.get('status', 'offline'))} | {_valve_badge(valve.get('state', 'CLOSED'))}",
                unsafe_allow_html=True,
            )
            if sensor:
                st.write(f"💧 {sensor.get('moisture', 0):.1f}% | 🌡️ {sensor.get('temperature', 0):.1f}°C | 💨 {sensor.get('humidity', 0):.1f}%")
                st.caption(f"Water: {valve.get('water_consumed_litres', 0):.2f} L")
            else:
                st.caption("No readings yet")

    st.divider()

    col_emg, col_note = st.columns([1, 2])
    with col_emg:
        st.markdown('<div class="emergency-btn">', unsafe_allow_html=True)
        if st.button("⛔ EMERGENCY — ALL VALVES OFF", width='stretch'):
            publish_emergency_off()
            st.error("EMERGENCY_OFF published to all 4 sector command topics!")
        st.markdown("</div>", unsafe_allow_html=True)
    with col_note:
        st.info("Emergency stop immediately broadcasts `EMERGENCY_OFF` (QoS 1, non-retained) to all 4 independent ESP32 nodes.")

    st.divider()

    st.markdown("### 🔔 Active Alerts")
    alerts_df = load_current_alerts()
    if alerts_df.empty:
        st.success("No unresolved alerts in database.")
    else:
        for _, row in alerts_df.head(15).iterrows():
            sev = str(row.get("severity", "WARNING")).upper()
            icon = "🔴" if sev == "CRITICAL" else "🟡"
            st.markdown(
                f"{icon} **[{sev}]** Sector {row.get('sector_id') or 'System'} — "
                f"`{row.get('alert_type', '')}` — {row.get('message', '')} "
                f"<small>({row.get('timestamp', '')})</small>",
                unsafe_allow_html=True,
            )

    if live_alerts:
        with st.expander("📡 Live MQTT Alert Stream", expanded=False):
            for a in reversed(live_alerts[-10:]):
                st.caption(f"{a['time']} — {a['topic']}: {a['payload']}")


def page_sector_cards(state: dict | None) -> None:
    st.title("🗺️ Sector Cards & Controls")
    if state is None:
        st.info("⏳ Waiting for master process...")
        return
    row1 = st.columns(2)
    row2 = st.columns(2)
    grid = [row1[0], row1[1], row2[0], row2[1]]
    for idx, sid in enumerate(SECTORS):
        render_sector_card(grid[idx], sid, state)


def page_live_charts() -> None:
    st.title("📈 Live Sensor Charts & Water Usage")
    df = load_sensor_history(limit=240)
    if df.empty:
        st.info("No sensor history in SQLite yet. Waiting for telemetry...")
        return

    st.subheader("💧 Soil Moisture Over Time (%)")
    pivot_m = df.pivot_table(index="timestamp", columns="sector_id", values="moisture", aggfunc="mean")
    pivot_m.columns = [f"Sector {c}" for c in pivot_m.columns]
    st.line_chart(pivot_m, width='stretch')

    st.subheader("🌡️ Ambient Temperature Over Time (°C)")
    pivot_t = df.pivot_table(index="timestamp", columns="sector_id", values="temperature", aggfunc="mean")
    pivot_t.columns = [f"Sector {c}" for c in pivot_t.columns]
    st.line_chart(pivot_t, width='stretch')

    st.subheader("💦 Cumulative Water Consumed (Litres)")
    pivot_w = df.pivot_table(index="timestamp", columns="sector_id", values="water_consumed_litres", aggfunc="max")
    pivot_w.columns = [f"Sector {c}" for c in pivot_w.columns]
    st.line_chart(pivot_w, width='stretch')


def page_event_log() -> None:
    st.title("📋 Event Log & Command Acknowledgments")

    st.subheader("Command → Acknowledgment Tracking")
    cmd_df = load_command_ack_history()
    if cmd_df.empty:
        st.info("No valve commands issued yet.")
    else:
        st.dataframe(cmd_df, width='stretch', hide_index=True)

    st.divider()
    st.subheader("System Event Log")
    fc1, fc2 = st.columns(2)
    sector_filter = fc1.selectbox(
        "Filter by Sector",
        options=["All", "Sector 1", "Sector 2", "Sector 3", "Sector 4"],
    )
    type_filter = fc2.selectbox(
        "Filter by Event Type",
        options=[
            "All", "COMMAND", "ACK", "ACK_TIMEOUT", "ALERT", "FAULT",
            "MODE_CHANGE", "SETTINGS_UPDATE", "EMERGENCY", "SYSTEM_START",
            "BROKER_CONNECTED", "BROKER_DISCONNECTED",
        ],
    )
    df = load_event_log(sector_filter, type_filter)
    if df.empty:
        st.info("No matching events recorded yet.")
    else:
        st.dataframe(df, width='stretch', hide_index=True)


def page_settings() -> None:
    st.title("⚙️ Threshold & Flow Rate Settings")
    cfg = load_settings()
    thresholds = cfg.get("thresholds", {})

    c1, c2 = st.columns(2)
    moisture_start = c1.number_input("Moisture START threshold (%)", 0.0, 100.0, float(thresholds.get("moisture_start", 30)), 1.0)
    moisture_stop = c2.number_input("Moisture STOP threshold (%)", 0.0, 100.0, float(thresholds.get("moisture_stop", 55)), 1.0)

    c3, c4 = st.columns(2)
    temp_alert = c3.number_input("High Temperature Alert (°C)", 0.0, 60.0, float(thresholds.get("temp_alert", 35)), 0.5)
    humidity_alert = c4.number_input("Low Humidity Alert (%)", 0.0, 100.0, float(thresholds.get("humidity_alert", 35)), 1.0)

    c5, c6, c7 = st.columns(3)
    new_flow = c5.number_input("Flow Rate (L/min per sector)", 0.1, 20.0, float(cfg.get("flow_rate_lpm", 2.0)), 0.1)
    stale_to = c6.number_input("Stale Data Timeout (s)", 5.0, 300.0, float(cfg.get("stale_data_timeout", 30)), 5.0)
    failsafe_to = c7.number_input("Node Fail-safe Timeout (s)", 10.0, 600.0, float(cfg.get("failsafe_timeout", 90)), 5.0)

    if st.button("💾 Save & Broadcast Settings", type="primary"):
        if moisture_start >= moisture_stop:
            st.error("Moisture START threshold must be strictly lower than STOP threshold (hysteresis band required).")
        else:
            cfg.setdefault("thresholds", {})
            cfg["thresholds"]["moisture_start"] = moisture_start
            cfg["thresholds"]["moisture_stop"] = moisture_stop
            cfg["thresholds"]["temp_alert"] = temp_alert
            cfg["thresholds"]["humidity_alert"] = humidity_alert
            cfg["flow_rate_lpm"] = new_flow
            cfg["stale_data_timeout"] = stale_to
            cfg["failsafe_timeout"] = failsafe_to
            save_settings(cfg)
            publish_settings(cfg)
            st.success("Settings saved to `config/settings.json` and broadcast over MQTT (`farm/system/config`).")

    with st.expander("Current config/settings.json"):
        st.json(cfg)


def page_fault_injection(state: dict | None) -> None:
    st.title("🧪 Fault Injection & Fail-Safe Testing")

    st.info(
        "**Command Published vs. Valve State Confirmed:** Publishing an `OPEN` or `CLOSE` command to "
        "`farm/sectorN/command` only requests an action (`desired_state`). The master does NOT confirm "
        "the valve state until the ESP32 node physically actuates and sends an `ACCEPTED` acknowledgment "
        "on `farm/sectorN/status`. Injecting a **Valve Fault** below simulates a hardware valve that fails "
        "to respond, causing an `ACK_TIMEOUT` alert."
    )

    sim_ctrl = _load_sim_control()
    cols = st.columns(4)
    for idx, sid in enumerate(SECTORS):
        sec_ctrl = sim_ctrl.get("sectors", {}).get(str(sid), {})
        is_disc = bool(sec_ctrl.get("disconnect", False))
        with cols[idx]:
            st.markdown(f"#### Sector {sid}")
            if is_disc:
                if st.button(f"🔌 Reconnect Node {sid}", key=f"reconn_{sid}", width='stretch'):
                    write_sector_fault(sid, "reconnect")
                    st.success(f"Reconnect signal sent to Sector {sid}")
            else:
                if st.button(f"✂️ Disconnect Node {sid}", key=f"disc_{sid}", width='stretch'):
                    write_sector_fault(sid, "disconnect")
                    st.warning(f"Sector {sid} disconnected from MQTT")

            if st.button(f"🕰️ Stale Data (45s)", key=f"stale_{sid}", width='stretch'):
                write_sector_fault(sid, "stale", duration_s=45.0)
                st.info(f"Stale data fault injected on Sector {sid}")

            if st.button(f"❌ Invalid Data", key=f"invalid_{sid}", width='stretch'):
                write_sector_fault(sid, "invalid")
                st.info(f"Invalid reading injected on Sector {sid}")

            if st.button(f"🕳️ Missing Telemetry", key=f"missing_{sid}", width='stretch'):
                write_sector_fault(sid, "missing")
                st.info(f"Missing telemetry injected on Sector {sid}")

            if st.button(f"🐢 Delayed Msg (10s)", key=f"delay_{sid}", width='stretch'):
                write_sector_fault(sid, "delay", delay_s=10.0)
                st.info(f"10s telemetry delay injected on Sector {sid}")

            if st.button(f"🔧 Valve Fault (35s)", key=f"vfault_{sid}", width='stretch'):
                write_sector_fault(sid, "valve_fault", duration_s=35.0)
                st.info(f"Valve unresponsive fault injected on Sector {sid}")

            if st.button(f"♻️ Restore Sector {sid}", key=f"restore_{sid}", width='stretch'):
                write_sector_fault(sid, "restore")
                st.success(f"Sector {sid} restored")

    st.divider()
    st.subheader("🌐 Global & Master Process Controls")
    gc1, gc2, gc3 = st.columns(3)

    with gc1:
        if st.button("♻️ RESTORE ALL SECTORS", width='stretch'):
            restore_all_faults()
            st.success("All node/sensor/valve faults cleared.")

    with gc2:
        st.markdown('<div class="emergency-btn">', unsafe_allow_html=True)
        if st.button("⛔ EMERGENCY ALL VALVES OFF", width='stretch'):
            publish_emergency_off()
            st.error("EMERGENCY_OFF sent to all 4 sectors!")
        st.markdown("</div>", unsafe_allow_html=True)

    with gc3:
        if st.button("🔄 Restart Master Process", width='stretch'):
            try:
                if os.name == "nt":
                    subprocess.run(
                        [
                            "powershell",
                            "-NoProfile",
                            "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'raspberry_pi_master' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
                        ],
                        timeout=5,
                        check=False,
                    )
                else:
                    subprocess.run(["pkill", "-f", "raspberry_pi_master.py"], timeout=5, check=False)
                time.sleep(1)
                subprocess.Popen(
                    [sys.executable, str(MASTER_SCRIPT)],
                    cwd=str(PROJECT_ROOT),
                    creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
                )
                st.success("Master Controller restarted!")
            except Exception as exc:
                st.error(f"Could not restart master: {exc}")

    if state and state.get("active_faults"):
        st.subheader("🔥 Currently Active Simulated Faults")
        for f in state["active_faults"]:
            st.warning(f"Sector {f.get('sector_id')} — `{f.get('fault_type')}` (since {f.get('since')})")


# ═════════════════════════════════════════════════════════════════════════════
# CLOUD CONTAINER RUNTIME BOOTSTRAP (Streamlit Community Cloud / Linux)
# ═════════════════════════════════════════════════════════════════════════════


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@st.cache_resource
def ensure_cloud_runtime() -> dict:
    """On Linux cloud hosts (e.g. Streamlit Community Cloud), launch Mosquitto,
    the Master process, and the 4 ESP32 node processes if not already running."""
    if os.name == "nt" or _port_open("127.0.0.1", 1883):
        return {"started": False}

    mosq = shutil.which("mosquitto")
    if not mosq:
        return {"started": False, "error": "mosquitto binary not found"}

    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
    procs = []
    try:
        procs.append(
            subprocess.Popen(
                [mosq, "-p", "1883"],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        for _ in range(30):
            if _port_open("127.0.0.1", 1883):
                break
            time.sleep(0.1)

        procs.append(subprocess.Popen([sys.executable, str(MASTER_SCRIPT)], cwd=str(PROJECT_ROOT)))
        time.sleep(1.0)
        for sid in SECTORS:
            node_script = PROJECT_ROOT / "esp32_nodes" / f"esp32_sector_{sid}.py"
            procs.append(subprocess.Popen([sys.executable, str(node_script)], cwd=str(PROJECT_ROOT)))
        time.sleep(1.5)
        return {"started": True, "pids": [p.pid for p in procs]}
    except Exception as exc:
        return {"started": False, "error": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# MAIN + 5-SECOND FRAGMENT AUTO-REFRESH
# ═════════════════════════════════════════════════════════════════════════════


def main() -> None:
    ensure_cloud_runtime()
    holder = get_mqtt_holder()
    holder.reconnect_if_needed()

    with st.sidebar:
        st.markdown("# 🌱 Smart Farm")
        st.caption("Virtual 4-Sector IoT Irrigation")
        st.divider()

        page = st.radio(
            "Navigation",
            options=[
                "🏠 Farm Overview",
                "🗺️ Sector Cards",
                "📈 Live Charts",
                "📋 Event Log",
                "⚙️ Settings",
                "🧪 Fault Injection",
            ],
            index=0,
        )

        st.divider()
        mqtt_ok, _, _ = holder.snapshot()
        mqtt_span = (
            '<span class="status-green">● Connected</span>'
            if mqtt_ok
            else '<span class="status-red">● Disconnected</span>'
        )
        st.markdown(f"Dashboard MQTT: {mqtt_span}", unsafe_allow_html=True)
        st.caption("Live data refreshes every 5 s")

    @st.fragment(run_every=5)
    def render_live_page() -> None:
        holder.reconnect_if_needed()
        conn_ok, err_msg, live_alerts = holder.snapshot()
        state = load_system_state()

        if page == "🏠 Farm Overview":
            page_overview(state, conn_ok, err_msg, live_alerts)
        elif page == "🗺️ Sector Cards":
            page_sector_cards(state)
        elif page == "📈 Live Charts":
            page_live_charts()
        elif page == "📋 Event Log":
            page_event_log()
        elif page == "⚙️ Settings":
            page_settings()
        elif page == "🧪 Fault Injection":
            page_fault_injection(state)

    render_live_page()


if __name__ == "__main__":
    main()
