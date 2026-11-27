"""
Smart Agriculture Irrigation System — Simplified Live Dashboard
Clean, presenter-friendly UI backed by MQTT (paho-mqtt), data/system_state.json,
and data/farm_history.db.
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
    page_title="Smart Farm Irrigation",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.2rem; padding-bottom: 1.5rem; }
    .flow-box {
        background: rgba(46, 204, 113, 0.08);
        border: 1px solid rgba(46, 204, 113, 0.30);
        border-radius: 10px;
        padding: 10px 14px;
        text-align: center;
        font-size: 0.92rem;
    }
    .pill-green { background:#1e4620; color:#6ee7b7; padding:2px 8px; border-radius:12px; font-size:0.8rem; font-weight:600; }
    .pill-amber { background:#4d3800; color:#fcd34d; padding:2px 8px; border-radius:12px; font-size:0.8rem; font-weight:600; }
    .pill-red   { background:#4c1d1d; color:#fca5a5; padding:2px 8px; border-radius:12px; font-size:0.8rem; font-weight:600; }
    .pill-gray  { background:#2d3139; color:#cbd5e1; padding:2px 8px; border-radius:12px; font-size:0.8rem; font-weight:600; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ═════════════════════════════════════════════════════════════════════════════
# THREAD-SAFE MQTT CLIENT
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
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"dashboard-{uuid.uuid4().hex[:6]}",
                protocol=mqtt.MQTTv311,
            )
            self.client.on_connect = self._on_connect_v2
            self.client.on_disconnect = self._on_disconnect_v2
        else:
            self.client = mqtt.Client(
                client_id=f"dashboard-{uuid.uuid4().hex[:6]}",
                protocol=mqtt.MQTTv311,
            )
            self.client.on_connect = self._on_connect_v1
            self.client.on_disconnect = self._on_disconnect_v1

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

    def _on_connect_v2(self, client, userdata, flags, reason_code, properties) -> None:
        ok = not reason_code.is_failure
        with self.lock:
            self.connected = ok
            if ok:
                self.error = ""
        if ok:
            client.subscribe("farm/system/alerts", qos=1)

    def _on_disconnect_v2(self, client, userdata, flags, reason_code, properties) -> None:
        with self.lock:
            self.connected = False

    def _on_connect_v1(self, client, userdata, flags, rc) -> None:
        ok = rc == 0
        with self.lock:
            self.connected = ok
            if ok:
                self.error = ""
        if ok:
            client.subscribe("farm/system/alerts", qos=1)

    def _on_disconnect_v1(self, client, userdata, rc) -> None:
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
            self.live_alerts = self.live_alerts[-30:]

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
    get_mqtt_holder().publish(
        f"farm/sector{sector_id}/command",
        {
            "cmd_id": str(uuid.uuid4()),
            "action": action,
            "sector_id": sector_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "dashboard",
        },
        qos=1,
    )


def publish_mode_change(sector_id: int, mode: str) -> None:
    get_mqtt_holder().publish(
        "farm/system/control",
        {
            "cmd_id": str(uuid.uuid4()),
            "action": "SET_MODE",
            "sector_id": sector_id,
            "mode": mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "dashboard",
        },
        qos=1,
    )


def publish_emergency_off() -> None:
    holder = get_mqtt_holder()
    for sid in SECTORS:
        holder.publish(
            f"farm/sector{sid}/command",
            {
                "cmd_id": str(uuid.uuid4()),
                "action": "EMERGENCY_OFF",
                "sector_id": sid,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "dashboard_emergency",
            },
            qos=1,
        )


def publish_settings(settings: dict) -> None:
    get_mqtt_holder().publish(
        "farm/system/config",
        {
            "cmd_id": str(uuid.uuid4()),
            "settings": settings,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "dashboard",
        },
        qos=1,
    )


# ═════════════════════════════════════════════════════════════════════════════
# SIMULATION CONTROL & DATA HELPERS
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


def load_sensor_history(limit: int = 200) -> pd.DataFrame:
    df = db_query(
        """
        SELECT sector_id, recorded_at AS timestamp, moisture, temperature, humidity
        FROM sensor_readings
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", errors="coerce")
    return df.dropna(subset=["timestamp"]).sort_values("timestamp")


def load_simple_activity_log(sector_filter: str = "All") -> pd.DataFrame:
    where = ""
    params: tuple = ()
    if sector_filter != "All":
        where = "WHERE sector_id = ?"
        params = (sector_filter.replace("Sector ", "").strip(),)

    df = db_query(
        f"""
        SELECT created_at AS Time, COALESCE(sector_id, 'System') AS Sector,
               event_type AS Event, description AS Details
        FROM events
        {where}
        ORDER BY id DESC
        LIMIT 80
        """,
        params,
    )
    if not df.empty:
        dt = pd.to_datetime(df["Time"], format="ISO8601", errors="coerce")
        df["Time"] = dt.dt.strftime("%H:%M:%S").fillna(df["Time"])
    return df


def load_current_alerts() -> pd.DataFrame:
    return db_query(
        """
        SELECT created_at AS timestamp, sector_id, alert_type, message, severity
        FROM alerts
        WHERE resolved = 0
        ORDER BY id DESC
        LIMIT 20
        """
    )


# ═════════════════════════════════════════════════════════════════════════════
# CLOUD RUNTIME BOOTSTRAP (Linux / Streamlit Community Cloud only)
# ═════════════════════════════════════════════════════════════════════════════


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@st.cache_resource
def ensure_cloud_runtime() -> dict:
    if os.name == "nt" or _port_open("127.0.0.1", 1883):
        return {"started": False}

    mosq = shutil.which("mosquitto")
    if not mosq:
        return {"started": False, "error": "mosquitto not found"}

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
            procs.append(
                subprocess.Popen(
                    [sys.executable, str(PROJECT_ROOT / "esp32_nodes" / f"esp32_sector_{sid}.py")],
                    cwd=str(PROJECT_ROOT),
                )
            )
        time.sleep(1.5)
        return {"started": True, "pids": [p.pid for p in procs]}
    except Exception as exc:
        return {"started": False, "error": str(exc)}


# ═════════════════════════════════════════════════════════════════════════════
# UI COMPONENTS
# ═════════════════════════════════════════════════════════════════════════════


def _render_sector_card(col, sector_id: int, state: dict, thresholds: dict) -> None:
    s_data = state.get("sectors", {}).get(str(sector_id), {})
    with col:
        with st.container(border=True):
            if not s_data:
                st.subheader(f"Sector {sector_id}")
                st.info("Waiting for node telemetry...")
                return

            sensor = s_data.get("sensor", {})
            valve = s_data.get("valve", {})
            node = s_data.get("node", {})
            decision = s_data.get("last_decision", {})
            mode = s_data.get("mode", "AUTO")
            pending_cnt = int(s_data.get("pending_cmds_count", 0))

            conn_status = node.get("status", "offline")
            valve_state = valve.get("state", "CLOSED")

            # Header row with clean visual pills
            if conn_status == "online":
                node_pill = '<span class="pill-green">● Online</span>'
            elif conn_status == "stale":
                node_pill = '<span class="pill-amber">● Stale / Invalid</span>'
            else:
                node_pill = '<span class="pill-red">● Offline</span>'

            if valve_state == "OPEN":
                valve_pill = '<span class="pill-green">💧 Watering (OPEN)</span>'
            else:
                valve_pill = '<span class="pill-gray">⏸️ Idle (CLOSED)</span>'

            mode_pill = (
                '<span class="pill-amber">MANUAL</span>'
                if mode == "MANUAL"
                else '<span class="pill-gray">AUTO</span>'
            )

            h_left, h_right = st.columns([2, 1])
            h_left.markdown(f"### Sector {sector_id}")
            h_right.markdown(f"<div style='text-align:right'>{mode_pill}</div>", unsafe_allow_html=True)
            st.markdown(f"{node_pill} &nbsp; {valve_pill}", unsafe_allow_html=True)

            if node.get("invalid_reason"):
                st.error(f"Bad reading blocked: {node['invalid_reason']}")

            # Key sensor numbers
            moisture = float(sensor.get("moisture", 0.0))
            temp = float(sensor.get("temperature", 0.0))
            humidity = float(sensor.get("humidity", 0.0))
            consumed = float(valve.get("water_consumed_litres", 0.0))
            flow = float(valve.get("flow_rate_lpm", 0.0)) if valve_state == "OPEN" else 0.0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Moisture", f"{moisture:.1f}%")
            m2.metric("Temp", f"{temp:.1f}°C")
            m3.metric("Humidity", f"{humidity:.0f}%")
            m4.metric("Water Used", f"{consumed:.2f} L", delta=f"{flow:.1f} L/m" if flow else None)

            # Visual moisture gauge relative to Start / Stop rules
            m_start = float(thresholds.get("moisture_start", 30))
            m_stop = float(thresholds.get("moisture_stop", 55))
            st.progress(min(max(moisture / 100.0, 0.0), 1.0))
            st.caption(f"Target band: Water below **{m_start:.0f}%** · Stop above **{m_stop:.0f}%**")

            # Plain-English rule explanation
            reason = decision.get("reason") or "Waiting for first sensor reading..."
            action = decision.get("action", "WAIT")
            if pending_cnt > 0:
                st.warning(f"⏳ Sent `{valve.get('desired_state')}` command — waiting for node confirmation...")
            elif action == "OPEN" or valve_state == "OPEN":
                st.success(f"**Rule Decision:** {reason}")
            elif decision.get("alerts"):
                st.warning(f"**Rule Decision:** {reason}")
            else:
                st.info(f"**Rule Decision:** {reason}")

            # Clean single control bar
            c_mode, c_adj = st.columns([2, 1])
            is_manual = c_mode.toggle(
                "Manual Control",
                value=(mode == "MANUAL"),
                key=f"manual_toggle_{sector_id}",
            )
            desired_mode = "MANUAL" if is_manual else "AUTO"
            if desired_mode != mode:
                publish_mode_change(sector_id, desired_mode)
                st.toast(f"Sector {sector_id} set to {desired_mode}")

            with c_adj.popover("🎛️ Adjust"):
                ov_m = st.slider("Moisture %", 0.0, 100.0, float(round(moisture, 1)), 1.0, key=f"sl_m_{sector_id}")
                ov_t = st.slider("Temp °C", 0.0, 50.0, float(round(temp, 1)), 0.5, key=f"sl_t_{sector_id}")
                ov_h = st.slider("Humidity %", 0.0, 100.0, float(round(humidity, 1)), 1.0, key=f"sl_h_{sector_id}")
                if st.button("Apply", key=f"apply_{sector_id}", width="stretch"):
                    write_manual_sensor_override(sector_id, ov_m, ov_t, ov_h)
                    st.success("Applied!")

            if is_manual:
                b1, b2 = st.columns(2)
                if b1.button("🟢 Open Valve", key=f"btn_open_{sector_id}", width="stretch"):
                    publish_valve_command(sector_id, "OPEN")
                    st.toast(f"OPEN sent to Sector {sector_id}")
                if b2.button("🔴 Close Valve", key=f"btn_close_{sector_id}", width="stretch"):
                    publish_valve_command(sector_id, "CLOSE")
                    st.toast(f"CLOSE sent to Sector {sector_id}")


# ═════════════════════════════════════════════════════════════════════════════
# TABS
# ═════════════════════════════════════════════════════════════════════════════


def tab_live_monitor(state: dict | None) -> None:
    # Simple visual flow diagram right at top so it's easy to explain
    f1, f2, f3, f4 = st.columns(4)
    f1.markdown('<div class="flow-box"><b>1. 4× Virtual ESP32s</b><br>Measure soil & run valves</div>', unsafe_allow_html=True)
    f2.markdown('<div class="flow-box"><b>2. Mosquitto MQTT</b><br>Delivers live JSON messages</div>', unsafe_allow_html=True)
    f3.markdown('<div class="flow-box"><b>3. Raspberry Pi Master</b><br>Applies IF/ELSE rules + logs DB</div>', unsafe_allow_html=True)
    f4.markdown('<div class="flow-box"><b>4. Live Dashboard</b><br>Shows status & sends commands</div>', unsafe_allow_html=True)

    st.write("")

    if state is None:
        st.warning("⏳ Waiting for Master Controller to publish its first update...")
        return

    master_ok = state.get("master_online", False)
    online_nodes = state.get("online_node_count", 0)
    active_valves = state.get("active_valve_count", 0)
    total_water = state.get("total_water_consumed_litres", 0.0)
    thresholds = state.get("thresholds", {"moisture_start": 30, "moisture_stop": 55})

    # Top KPI bar + Emergency button
    k1, k2, k3, k4, k5 = st.columns([1.2, 1, 1, 1.2, 1.6])
    k1.metric("Master Brain", "🟢 Online" if master_ok else "🔴 Offline")
    k2.metric("Nodes Online", f"{online_nodes} / 4")
    k3.metric("Valves Open", f"{active_valves} / 4")
    k4.metric("Total Water", f"{total_water:.2f} L")
    with k5:
        st.write("")
        if st.button("⛔ EMERGENCY STOP ALL VALVES", type="primary", width="stretch"):
            publish_emergency_off()
            st.error("Emergency STOP sent to all 4 ESP32 nodes!")

    st.divider()

    # 2x2 Sector Grid
    r1 = st.columns(2)
    r2 = st.columns(2)
    grid = [r1[0], r1[1], r2[0], r2[1]]
    for idx, sid in enumerate(SECTORS):
        _render_sector_card(grid[idx], sid, state, thresholds)

    # Active Alerts summary
    alerts_df = load_current_alerts()
    if alerts_df.empty:
        st.success("✅ No active system alerts — all sectors operating normally.")
    else:
        with st.container(border=True):
            st.markdown(f"**🔔 Active Alerts ({len(alerts_df)})**")
            for _, row in alerts_df.head(6).iterrows():
                sec_lbl = f"Sector {row['sector_id']}" if row["sector_id"] else "System"
                st.warning(f"**{sec_lbl}** — {row['message']}")


def tab_charts_and_logs() -> None:
    df = load_sensor_history(limit=200)
    if df.empty:
        st.info("Waiting for sensor readings to build charts...")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("💧 Soil Moisture (%)")
            piv_m = df.pivot_table(index="timestamp", columns="sector_id", values="moisture", aggfunc="mean")
            piv_m.columns = [f"Sector {c}" for c in piv_m.columns]
            st.line_chart(piv_m, width="stretch")
        with c2:
            st.subheader("🌡️ Temperature (°C)")
            piv_t = df.pivot_table(index="timestamp", columns="sector_id", values="temperature", aggfunc="mean")
            piv_t.columns = [f"Sector {c}" for c in piv_t.columns]
            st.line_chart(piv_t, width="stretch")

    st.divider()
    h1, h2 = st.columns([3, 1])
    h1.subheader("📋 Recent Activity Log (Commands, Node ACKs & Alerts)")
    sector_filter = h2.selectbox(
        "Filter Sector",
        ["All", "Sector 1", "Sector 2", "Sector 3", "Sector 4"],
        label_visibility="collapsed",
    )
    act_df = load_simple_activity_log(sector_filter)
    if act_df.empty:
        st.info("No events recorded yet.")
    else:
        st.dataframe(act_df, width="stretch", hide_index=True)


def tab_rules_and_faults(state: dict | None) -> None:
    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            st.subheader("⚙️ Irrigation Rules (Rule-Based Engine)")
            st.caption("Deterministic threshold rules (not a trained ML model). Easy to tune live:")
            cfg = load_settings()
            th = cfg.get("thresholds", {})

            m_start = st.number_input("Start watering when moisture < (%)", 0.0, 100.0, float(th.get("moisture_start", 30)), 1.0)
            m_stop = st.number_input("Stop watering when moisture > (%)", 0.0, 100.0, float(th.get("moisture_stop", 55)), 1.0)
            c_a, c_b = st.columns(2)
            t_alert = c_a.number_input("High Temp Alert (°C)", 0.0, 60.0, float(th.get("temp_alert", 35)), 0.5)
            h_alert = c_b.number_input("Low Humidity Alert (%)", 0.0, 100.0, float(th.get("humidity_alert", 35)), 1.0)
            flow = st.number_input("Valve Flow Rate (L/min)", 0.1, 20.0, float(cfg.get("flow_rate_lpm", 2.0)), 0.1)

            if st.button("💾 Save & Apply Rules", type="primary", width="stretch"):
                if m_start >= m_stop:
                    st.error("Start threshold must be lower than Stop threshold.")
                else:
                    cfg.setdefault("thresholds", {})
                    cfg["thresholds"].update({
                        "moisture_start": m_start,
                        "moisture_stop": m_stop,
                        "temp_alert": t_alert,
                        "humidity_alert": h_alert,
                    })
                    cfg["flow_rate_lpm"] = flow
                    save_settings(cfg)
                    publish_settings(cfg)
                    st.success("Rules saved and sent to Master & ESP32 nodes!")

    with right:
        with st.container(border=True):
            st.subheader("🧪 Fault & Fail-Safe Demo")
            st.caption("Demonstrate how the system handles failures safely without hardware damage:")

            target_sid = st.selectbox("Choose Sector to Test", SECTORS, format_func=lambda s: f"Sector {s}")
            sim_ctrl = _load_sim_control()
            is_disc = bool(sim_ctrl.get("sectors", {}).get(str(target_sid), {}).get("disconnect", False))

            b1, b2 = st.columns(2)
            if is_disc:
                if b1.button("🔌 Reconnect Node", width="stretch"):
                    write_sector_fault(target_sid, "reconnect")
                    st.success(f"Sector {target_sid} reconnecting...")
            else:
                if b1.button("✂️ Disconnect Node", width="stretch"):
                    write_sector_fault(target_sid, "disconnect")
                    st.warning(f"Sector {target_sid} disconnected (Master will mark Offline).")

            if b2.button("❌ Send Bad Sensor Data", width="stretch"):
                write_sector_fault(target_sid, "invalid")
                st.info("Sent out-of-range reading — Master will reject it.")

            b3, b4 = st.columns(2)
            if b3.button("🕰️ Freeze Sensor (Stale)", width="stretch"):
                write_sector_fault(target_sid, "stale", duration_s=45.0)
                st.info("Sensor frozen for 45s — Master will pause auto decisions.")

            if b4.button("🔧 Break Valve (No ACK)", width="stretch"):
                write_sector_fault(target_sid, "valve_fault", duration_s=35.0)
                st.info("Valve ignores commands — triggers ACK Timeout.")

            c_fix, c_rst = st.columns(2)
            if c_fix.button("♻️ Fix All Faults", type="primary", width="stretch"):
                restore_all_faults()
                st.success("All faults cleared!")

            if c_rst.button("🔄 Restart Master", width="stretch"):
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["powershell", "-NoProfile", "-Command",
                             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'raspberry_pi_master' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                            timeout=5, check=False,
                        )
                    else:
                        subprocess.run(["pkill", "-f", "raspberry_pi_master.py"], timeout=5, check=False)
                    time.sleep(1)
                    subprocess.Popen(
                        [sys.executable, str(MASTER_SCRIPT)],
                        cwd=str(PROJECT_ROOT),
                        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
                    )
                    st.success("Master restarted!")
                except Exception as exc:
                    st.error(f"Restart failed: {exc}")

            st.caption(
                "**Why ACKs matter:** Publishing a command only *asks* a valve to open; the Master waits "
                "for the ESP32 node's `ACCEPTED` reply before confirming the valve actually changed."
            )

    if state and state.get("active_faults"):
        st.warning("Active simulated faults: " + ", ".join(
            f"Sector {f['sector_id']} ({f['fault_type']})" for f in state["active_faults"]
        ))


# ═════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ═════════════════════════════════════════════════════════════════════════════


def main() -> None:
    ensure_cloud_runtime()
    holder = get_mqtt_holder()
    holder.reconnect_if_needed()

    with st.sidebar:
        st.title("🌱 Smart Farm")
        st.caption("Virtual Distributed IoT Irrigation")
        mqtt_ok, _, _ = holder.snapshot()
        st.markdown(
            "Broker: " + ('<span class="pill-green">Connected</span>' if mqtt_ok else '<span class="pill-red">Disconnected</span>'),
            unsafe_allow_html=True,
        )
        st.divider()
        st.markdown("### 🗣️ How to Explain This")
        st.markdown(
            """
1. **4 Independent Nodes:** Each sector runs as its own Python process simulating an ESP32 + soil sensor + water valve.
2. **Real MQTT Messaging:** Nodes never talk to the dashboard directly — everything goes through the **Mosquitto** broker.
3. **Transparent Rule Engine:** The Raspberry Pi Master checks moisture every 5s (`<30%` Open, `>55%` Close, `30–55%` Hold to avoid flickering).
4. **Safety First:** Bad/stale readings are ignored, commands require node ACKs, and nodes auto-close valves if contact is lost.
            """
        )
        st.caption("Auto-updates every 5 seconds")

    st.title("🌱 Smart Agriculture Irrigation Simulation")

    @st.fragment(run_every=5)
    def render_live() -> None:
        holder.reconnect_if_needed()
        state = load_system_state()
        t1, t2, t3 = st.tabs(["🌿 Live Farm Monitor", "📈 Charts & Logs", "⚙️ Rules & Fault Demo"])
        with t1:
            tab_live_monitor(state)
        with t2:
            tab_charts_and_logs()
        with t3:
            tab_rules_and_faults(state)

    render_live()


if __name__ == "__main__":
    main()
