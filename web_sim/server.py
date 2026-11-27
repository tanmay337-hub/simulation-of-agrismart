"""
web_sim/server.py — Real-time WebSocket + REST bridge for the Three.js / Anime.js
3D Smart Agriculture Web Simulation.

Serves web_sim/ on http://localhost:8080 and bridges live MQTT + SQLite +
sim_control.json between the 4 ESP32 processes, Raspberry Pi 5 Master, and browser.
"""

import asyncio
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import uuid
from typing import Any

import paho.mqtt.client as mqtt
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect
import uvicorn

WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_FILE = DATA_DIR / "system_state.json"
DB_FILE = DATA_DIR / "farm_history.db"
CFG_FILE = PROJECT_ROOT / "config" / "settings.json"
SIM_CTRL_FILE = DATA_DIR / "sim_control.json"

SECTORS = [1, 2, 3, 4]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {} if default is None else default


def _save_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


class MQTTBridge:
    """Thread-safe MQTT observer + command publisher."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.connected = False
        self.packets: deque[dict[str, Any]] = deque(maxlen=150)
        cfg = _load_json(CFG_FILE, {})
        mqtt_cfg = cfg.get("mqtt", {})
        self.broker = mqtt_cfg.get("broker", "localhost")
        self.port = int(mqtt_cfg.get("port", 1883))

        if hasattr(mqtt, "CallbackAPIVersion"):
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"web_bridge_{uuid.uuid4().hex[:6]}",
                protocol=mqtt.MQTTv311,
            )
            self.client.on_connect = self._on_connect_v2
            self.client.on_disconnect = self._on_disconnect_v2
        else:
            self.client = mqtt.Client(
                client_id=f"web_bridge_{uuid.uuid4().hex[:6]}",
                protocol=mqtt.MQTTv311,
            )
            self.client.on_connect = self._on_connect_v1
            self.client.on_disconnect = self._on_disconnect_v1
        self.client.on_message = self._on_message
        self._connect_async()

    def _connect_async(self) -> None:
        def _run() -> None:
            while True:
                try:
                    self.client.connect(self.broker, self.port, keepalive=60)
                    self.client.loop_start()
                    return
                except Exception:
                    threading.Event().wait(3.0)

        threading.Thread(target=_run, daemon=True, name="web-mqtt-connect").start()

    def _on_connect_v2(self, client, userdata, flags, reason_code, properties) -> None:
        ok = not reason_code.is_failure
        with self.lock:
            self.connected = ok
        if ok:
            client.subscribe("farm/#", qos=1)

    def _on_disconnect_v2(self, client, userdata, flags, reason_code, properties) -> None:
        with self.lock:
            self.connected = False

    def _on_connect_v1(self, client, userdata, flags, rc) -> None:
        with self.lock:
            self.connected = rc == 0
        if rc == 0:
            client.subscribe("farm/#", qos=1)

    def _on_disconnect_v1(self, client, userdata, rc) -> None:
        with self.lock:
            self.connected = False

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            payload = {"raw": msg.payload.decode("utf-8", errors="replace")}
        entry = {
            "id": uuid.uuid4().hex[:8],
            "topic": msg.topic,
            "payload": payload,
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "timestamp": _now_iso(),
        }
        with self.lock:
            self.packets.append(entry)

    def publish(self, topic: str, payload: dict[str, Any], qos: int = 1) -> bool:
        try:
            res = self.client.publish(topic, json.dumps(payload), qos=qos, retain=False)
            return res.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception:
            return False

    def recent_packets(self, limit: int = 40) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.packets)[-limit:]


bridge = MQTTBridge()


def _query_db(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    if not DB_FILE.exists():
        return []
    try:
        conn = sqlite3.connect(DB_FILE, timeout=3)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _build_snapshot() -> dict[str, Any]:
    state = _load_json(STATE_FILE, None)
    cfg = _load_json(CFG_FILE, {})
    sim_ctrl = _load_json(SIM_CTRL_FILE, {"crisis": "normal", "sectors": {}})

    # Check if master timestamp is fresh (< 15s)
    master_alive = False
    if isinstance(state, dict) and state.get("timestamp"):
        try:
            ts = datetime.fromisoformat(str(state["timestamp"]).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            master_alive = bool(state.get("master_online", False)) and age <= 15.0
            state["master_online"] = master_alive
        except Exception:
            pass

    history = _query_db(
        "SELECT sector_id, moisture, temperature, humidity, flow_rate_lpm, water_consumed_litres, recorded_at AS timestamp "
        "FROM sensor_readings ORDER BY id DESC LIMIT 160"
    )
    alerts = _query_db(
        "SELECT sector_id, alert_type, message, severity, created_at AS timestamp "
        "FROM alerts WHERE resolved = 0 ORDER BY id DESC LIMIT 25"
    )
    events = _query_db(
        "SELECT sector_id, event_type, description, created_at AS timestamp "
        "FROM events ORDER BY id DESC LIMIT 40"
    )

    return {
        "backend_online": master_alive,
        "bridge_mqtt_connected": bridge.connected,
        "state": state,
        "config": cfg,
        "sim_control": sim_ctrl,
        "history": list(reversed(history)),
        "alerts": alerts,
        "events": events,
        "mqtt_packets": bridge.recent_packets(35),
        "server_time": _now_iso(),
    }


async def api_state(request):
    return JSONResponse(_build_snapshot())


async def api_command(request):
    body = await request.json()
    action = str(body.get("action", "")).upper()
    if action == "EMERGENCY_OFF":
        for sid in SECTORS:
            bridge.publish(
                f"farm/sector{sid}/command",
                {
                    "cmd_id": str(uuid.uuid4()),
                    "action": "EMERGENCY_OFF",
                    "sector_id": sid,
                    "timestamp": _now_iso(),
                    "source": "web_sim",
                },
            )
        return JSONResponse({"ok": True, "action": "EMERGENCY_OFF"})

    sid = int(body.get("sector_id", 1))
    if sid not in SECTORS or action not in ("OPEN", "CLOSE"):
        return JSONResponse({"ok": False, "error": "Invalid sector or action"}, status_code=400)
    ok = bridge.publish(
        f"farm/sector{sid}/command",
        {
            "cmd_id": str(uuid.uuid4()),
            "action": action,
            "sector_id": sid,
            "timestamp": _now_iso(),
            "source": "web_sim",
        },
    )
    return JSONResponse({"ok": ok, "sector_id": sid, "action": action})


async def api_mode(request):
    body = await request.json()
    sid = int(body.get("sector_id", 1))
    mode = str(body.get("mode", "AUTO")).upper()
    if sid not in SECTORS or mode not in ("AUTO", "MANUAL"):
        return JSONResponse({"ok": False, "error": "Invalid mode"}, status_code=400)
    ok = bridge.publish(
        "farm/system/control",
        {
            "cmd_id": str(uuid.uuid4()),
            "action": "SET_MODE",
            "sector_id": sid,
            "mode": mode,
            "timestamp": _now_iso(),
            "source": "web_sim",
        },
    )
    return JSONResponse({"ok": ok, "sector_id": sid, "mode": mode})


def _notify_sync(crisis: str = "normal") -> None:
    bridge.publish(
        "farm/system/control",
        {
            "cmd_id": str(uuid.uuid4()),
            "action": "SYNC_SIM",
            "crisis": crisis,
            "timestamp": _now_iso(),
            "source": "web_sim",
        },
        qos=1,
    )


async def api_sensor_fault(request):
    body = await request.json()
    sid = str(int(body.get("sector_id", 1)))
    sensor = str(body.get("sensor", "moisture"))
    mode = str(body.get("mode", "ok"))
    ctrl = _load_json(SIM_CTRL_FILE, {"crisis": "normal", "sectors": {}})
    sec = ctrl.setdefault("sectors", {}).setdefault(sid, {})
    sec.setdefault("sensor_faults", {})[sensor] = mode
    sec["updated_at"] = _now_iso()
    _save_json_atomic(SIM_CTRL_FILE, ctrl)
    _notify_sync(ctrl.get("crisis", "normal"))
    return JSONResponse({"ok": True, "sector_id": sid, "sensor": sensor, "mode": mode})


async def api_valve_fault(request):
    body = await request.json()
    sid = str(int(body.get("sector_id", 1)))
    mode = str(body.get("mode", "normal"))
    ctrl = _load_json(SIM_CTRL_FILE, {"crisis": "normal", "sectors": {}})
    sec = ctrl.setdefault("sectors", {}).setdefault(sid, {})
    sec["valve_fault_mode"] = mode
    sec["updated_at"] = _now_iso()
    _save_json_atomic(SIM_CTRL_FILE, ctrl)
    _notify_sync(ctrl.get("crisis", "normal"))
    return JSONResponse({"ok": True, "sector_id": sid, "valve_fault_mode": mode})


async def api_node_disconnect(request):
    body = await request.json()
    sid = str(int(body.get("sector_id", 1)))
    disconnect = bool(body.get("disconnect", False))
    ctrl = _load_json(SIM_CTRL_FILE, {"crisis": "normal", "sectors": {}})
    sec = ctrl.setdefault("sectors", {}).setdefault(sid, {})
    sec["disconnect"] = disconnect
    sec["updated_at"] = _now_iso()
    _save_json_atomic(SIM_CTRL_FILE, ctrl)
    _notify_sync(ctrl.get("crisis", "normal"))
    return JSONResponse({"ok": True, "sector_id": sid, "disconnect": disconnect})


async def api_crisis(request):
    body = await request.json()
    crisis = str(body.get("crisis", "normal"))
    ctrl = _load_json(SIM_CTRL_FILE, {"crisis": "normal", "sectors": {}})
    ctrl["crisis"] = crisis
    _save_json_atomic(SIM_CTRL_FILE, ctrl)
    _notify_sync(crisis)
    return JSONResponse({"ok": True, "crisis": crisis})


async def api_manual_sensor(request):
    body = await request.json()
    sid = str(int(body.get("sector_id", 1)))
    ctrl = _load_json(SIM_CTRL_FILE, {"crisis": "normal", "sectors": {}})
    sec = ctrl.setdefault("sectors", {}).setdefault(sid, {})
    sec["manual_override"] = {
        "nonce": str(uuid.uuid4()),
        "moisture": float(body.get("moisture", 30.0)),
        "temperature": float(body.get("temperature", 28.0)),
        "humidity": float(body.get("humidity", 50.0)),
    }
    sec["updated_at"] = _now_iso()
    _save_json_atomic(SIM_CTRL_FILE, ctrl)
    _notify_sync(ctrl.get("crisis", "normal"))
    return JSONResponse({"ok": True, "sector_id": sid})


async def api_thresholds(request):
    body = await request.json()
    cfg = _load_json(CFG_FILE, {})
    th = cfg.setdefault("thresholds", {})
    for k in ("moisture_start", "moisture_stop", "temp_alert", "humidity_alert"):
        if k in body:
            th[k] = float(body[k])
    if "flow_rate_lpm" in body:
        cfg["flow_rate_lpm"] = float(body["flow_rate_lpm"])
    _save_json_atomic(CFG_FILE, cfg)
    bridge.publish(
        "farm/system/config",
        {
            "cmd_id": str(uuid.uuid4()),
            "settings": cfg,
            "timestamp": _now_iso(),
            "source": "web_sim",
        },
    )
    return JSONResponse({"ok": True, "config": cfg})


async def api_restore_all(request):
    ctrl = {"crisis": "normal", "sectors": {}}
    for sid in SECTORS:
        ctrl["sectors"][str(sid)] = {
            "disconnect": False,
            "fault": "restore",
            "fault_nonce": str(uuid.uuid4()),
            "valve_fault_mode": "normal",
            "sensor_faults": {
                "moisture": "ok",
                "temperature": "ok",
                "humidity": "ok",
                "light_lux": "ok",
                "flow": "ok",
            },
            "updated_at": _now_iso(),
        }
    _save_json_atomic(SIM_CTRL_FILE, ctrl)
    _notify_sync("normal")
    return JSONResponse({"ok": True})


async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(_build_snapshot())
            await asyncio.sleep(0.45)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


routes = [
    Route("/api/state", api_state, methods=["GET"]),
    Route("/api/command", api_command, methods=["POST"]),
    Route("/api/mode", api_mode, methods=["POST"]),
    Route("/api/sensor_fault", api_sensor_fault, methods=["POST"]),
    Route("/api/valve_fault", api_valve_fault, methods=["POST"]),
    Route("/api/node_disconnect", api_node_disconnect, methods=["POST"]),
    Route("/api/crisis", api_crisis, methods=["POST"]),
    Route("/api/manual_sensor", api_manual_sensor, methods=["POST"]),
    Route("/api/thresholds", api_thresholds, methods=["POST"]),
    Route("/api/restore_all", api_restore_all, methods=["POST"]),
    WebSocketRoute("/ws", ws_endpoint),
    Mount("/", app=StaticFiles(directory=str(WEB_DIR), html=True), name="static"),
]

app = Starlette(routes=routes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning")
