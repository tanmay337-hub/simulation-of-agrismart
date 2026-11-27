/**
 * sim_engine.js — Dual-mode controller:
 *   1) LIVE MQTT BACKEND MODE: connects via WebSocket + REST to web_sim/server.py
 *      (real Mosquitto + 4 ESP32 processes + Raspberry Pi 5 Master).
 *   2) BROWSER SANDBOX FALLBACK: if server.py is not running (e.g. static preview),
 *      runs an identical 4-node ESP32 + RPi 5 Rule Engine loop in the browser.
 */

const INITIAL_SECTORS = {
  1: { moisture: 22.0, temperature: 29.0, humidity: 48.0, light_lux: 34800 },
  2: { moisture: 68.0, temperature: 32.0, humidity: 42.0, light_lux: 35100 },
  3: { moisture: 37.0, temperature: 36.0, humidity: 31.0, light_lux: 35400 },
  4: { moisture: 18.0, temperature: 27.0, humidity: 55.0, light_lux: 34600 },
};

export class SimController {
  constructor(onUpdate, onPacket, onLog) {
    this.onUpdate = onUpdate;
    this.onPacket = onPacket;
    this.onLog = onLog;
    this.mode = "connecting"; // "backend" | "sandbox"
    this.ws = null;
    this.seenPacketIds = new Set();
    this.history = { 1: [], 2: [], 3: [], 4: [] };
    this.activityBuckets = [];
    this.currentBucket = { sensors: 0, commands: 0, acks: 0, alerts: 0, total: 0 };

    // Browser sandbox fallback state
    this.sandbox = this._createSandboxState();
    this._start();
  }

  _createSandboxState() {
    const sectors = {};
    for (const sid of [1, 2, 3, 4]) {
      const init = INITIAL_SECTORS[sid];
      sectors[String(sid)] = {
        sensor: {
          node_id: `esp32_sector_${sid}`,
          sector_id: sid,
          moisture: init.moisture,
          temperature: init.temperature,
          humidity: init.humidity,
          light_lux: init.light_lux,
          sequence_number: 0,
          flow_rate_lpm: 0,
          water_consumed_litres: 0,
        },
        sensor_health: {
          moisture: "ok",
          temperature: "ok",
          humidity: "ok",
          light_lux: "ok",
          flow: "ok",
        },
        channel_errors: {},
        valve: {
          state: "CLOSED",
          desired_state: "CLOSED",
          fault_mode: "normal",
          flow_rate_lpm: 0,
          water_consumed_litres: 0,
        },
        node: {
          status: "online",
          node_online: true,
          stale: false,
          reading_valid: true,
          invalid_reason: "",
          last_seen_ago: 0,
          disconnected: false,
        },
        last_decision: {
          action: "WAIT",
          reason: "Initialising RPi 5 rule engine...",
          alerts: [],
        },
        mode: "AUTO",
        pending_cmds_count: 0,
      };
    }
    return {
      master_online: true,
      broker_connected: true,
      online_node_count: 4,
      active_valve_count: 0,
      total_water_consumed_litres: 0,
      alert_count: 0,
      crisis: "normal",
      thresholds: {
        moisture_start: 30,
        moisture_stop: 55,
        temp_alert: 35,
        humidity_alert: 35,
      },
      flow_rate_lpm: 2.0,
      sectors,
      _phys: JSON.parse(JSON.stringify(INITIAL_SECTORS)),
      _frozen: {},
    };
  }

  async _start() {
    // Roll activity chart buckets every 3s
    setInterval(() => {
      this.activityBuckets.push({ ...this.currentBucket });
      if (this.activityBuckets.length > 28) this.activityBuckets.shift();
      this.currentBucket = { sensors: 0, commands: 0, acks: 0, alerts: 0, total: 0 };
    }, 3000);

    // Try backend WebSocket if served over HTTP(S)
    if (location.protocol.startsWith("http")) {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 1200);
      try {
        const res = await fetch("api/state", { cache: "no-store", signal: ctrl.signal });
        clearTimeout(timer);
        if (res.ok) {
          const snap = await res.json();
          if (snap && (snap.backend_online || snap.bridge_mqtt_connected)) {
            this.mode = "backend";
            this._handleBackendSnapshot(snap);
            this._connectWS();
            return;
          }
        }
      } catch {
        clearTimeout(timer);
        // Fall through to browser sandbox
      }
    }
    this._startSandbox();
  }

  _connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${proto}//${location.host}/ws`);
    this.ws.onmessage = (ev) => {
      try {
        const snap = JSON.parse(ev.data);
        if (snap.backend_online || snap.bridge_mqtt_connected) {
          this.mode = "backend";
          this._handleBackendSnapshot(snap);
        } else if (this.mode !== "sandbox") {
          this._startSandbox();
        }
      } catch {}
    };
    this.ws.onerror = () => {
      if (this.mode !== "sandbox") this._startSandbox();
    };
    this.ws.onclose = () => {
      if (this.mode === "backend") {
        setTimeout(() => this._connectWS(), 2500);
      }
    };
  }

  _handleBackendSnapshot(snap) {
    // Hydrate charts from SQLite history
    const hMap = { 1: [], 2: [], 3: [], 4: [] };
    for (const row of snap.history || []) {
      const sid = Number(row.sector_id);
      if (hMap[sid]) hMap[sid].push(row);
    }
    for (const sid of [1, 2, 3, 4]) {
      this.history[sid] = hMap[sid].slice(-45);
    }

    // Emit new MQTT packet animations & activity log items
    for (const pkt of snap.mqtt_packets || []) {
      if (this.seenPacketIds.has(pkt.id)) continue;
      this.seenPacketIds.add(pkt.id);
      if (this.seenPacketIds.size > 400) {
        const first = this.seenPacketIds.values().next().value;
        this.seenPacketIds.delete(first);
      }
      const parts = pkt.topic.split("/");
      const secMatch = parts[1]?.match(/^sector(\d)$/);
      const sid = secMatch ? Number(secMatch[1]) : null;
      const msgType = parts[2];

      if (msgType === "sensors") {
        this._bumpActivity("sensors");
        if (sid) this.onPacket(sid, "telemetry");
        const p = pkt.payload || {};
        this.onLog({
          time: pkt.time,
          sector: sid || "Sys",
          kind: "SENSORS",
          text: `${pkt.topic} → M:${p.moisture ?? "ERR"}% T:${p.temperature ?? "ERR"}°C H:${p.humidity ?? "ERR"}% Flow:${p.flow_rate_lpm ?? "ERR"}`,
        });
      } else if (msgType === "command") {
        this._bumpActivity("commands");
        if (sid) this.onPacket(sid, "command");
        const p = pkt.payload || {};
        this.onLog({
          time: pkt.time,
          sector: sid || "Sys",
          kind: "COMMAND",
          text: `${pkt.topic} → ${p.action} (${p.source || "master"})`,
        });
      } else if (msgType === "status" && parts[1] !== "system") {
        this._bumpActivity("acks");
        if (sid) this.onPacket(sid, "telemetry");
        const p = pkt.payload || {};
        this.onLog({
          time: pkt.time,
          sector: sid || "Sys",
          kind: "ACK",
          text: `${pkt.topic} → ${p.status} valve=${p.valve_state} (${p.reason || ""})`,
        });
      } else if (pkt.topic === "farm/system/alerts") {
        this._bumpActivity("alerts");
        if (sid || pkt.payload?.sector_id) this.onPacket(sid || Number(pkt.payload.sector_id), "alert");
        this.onLog({
          time: pkt.time,
          sector: pkt.payload?.sector_id || "Sys",
          kind: "ALERT",
          text: `${pkt.payload?.alert_type || "alert"}: ${pkt.payload?.message || ""}`,
        });
      }
    }

    if (snap.state) {
      this.onUpdate(snap.state, this.mode, snap.sim_control);
    }
  }

  _bumpActivity(kind) {
    this.currentBucket[kind] += 1;
    this.currentBucket.total += 1;
  }

  // ── BROWSER SANDBOX ENGINE (runs when Python bridge isn't present) ──

  _startSandbox() {
    if (this._sandboxTimer) return;
    this.mode = "sandbox";
    this._tickSandbox();
    this._sandboxTimer = setInterval(() => this._tickSandbox(), 2200);
  }

  _tickSandbox() {
    const sb = this.sandbox;
    const crisis = sb.crisis;
    const brokerDown = crisis === "broker_outage";
    sb.broker_connected = !brokerDown;
    const nowStr = new Date().toTimeString().slice(0, 8);

    let onlineCount = 0;
    let openValves = 0;
    let totalWater = 0;

    for (const sid of [1, 2, 3, 4]) {
      const sec = sb.sectors[String(sid)];
      const phys = sb._phys[sid];
      const vMode = sec.valve.fault_mode;
      const vOpen = sec.valve.state === "OPEN";

      // Effective physical flow
      let effFlow = 0;
      if (crisis === "water_supply_failure") effFlow = 0;
      else if (vOpen) effFlow = sb.flow_rate_lpm;
      else if (vMode === "leak") effFlow = Number((sb.flow_rate_lpm * 0.4).toFixed(2));

      // Accumulate water
      if (effFlow > 0) {
        sec.valve.water_consumed_litres = Number((sec.valve.water_consumed_litres + effFlow * (2.2 / 60)).toFixed(3));
      }
      totalWater += sec.valve.water_consumed_litres;

      // Environmental physics
      if (crisis === "heatwave") {
        phys.moisture += effFlow > 0 ? 0.3 : -1.1;
        phys.temperature += (42 - phys.temperature) * 0.14;
        phys.humidity += (18 - phys.humidity) * 0.14;
        phys.light_lux += (78000 - phys.light_lux) * 0.15;
      } else if (crisis === "rainstorm") {
        phys.moisture += 0.9 + (effFlow > 0 ? 0.4 : 0);
        phys.temperature += (21 - phys.temperature) * 0.12;
        phys.humidity += (94 - phys.humidity) * 0.16;
        phys.light_lux += (4500 - phys.light_lux) * 0.2;
      } else if (crisis === "frost") {
        phys.moisture += effFlow > 0 ? 0.55 : -0.12;
        phys.temperature += (1.0 - phys.temperature) * 0.15;
        phys.humidity += (82 - phys.humidity) * 0.1;
        phys.light_lux += (14000 - phys.light_lux) * 0.12;
      } else {
        phys.moisture += effFlow > 0 ? 0.65 : -0.35;
        const base = INITIAL_SECTORS[sid];
        phys.temperature += (base.temperature - phys.temperature) * 0.08 + (Math.random() - 0.5) * 0.25;
        phys.humidity += (base.humidity - phys.humidity) * 0.08 + (Math.random() - 0.5) * 0.35;
        phys.light_lux += (base.light_lux - phys.light_lux) * 0.08 + (Math.random() - 0.5) * 200;
      }
      phys.moisture = Math.max(0, Math.min(100, phys.moisture));
      phys.temperature = Math.max(-5, Math.min(55, phys.temperature));
      phys.humidity = Math.max(5, Math.min(100, phys.humidity));

      // Offline / broker outage handling
      if (sec.node.disconnected || brokerDown) {
        sec.node.status = "offline";
        sec.node.node_online = false;
        sec.node.last_seen_ago = Math.round((sec.node.last_seen_ago || 0) + 2.2);
        // Fail-safe auto-close after 25s in sandbox
        if (sec.node.last_seen_ago > 25 && sec.valve.state === "OPEN") {
          sec.valve.state = "CLOSED";
          this._bumpActivity("alerts");
          this.onLog({
            time: nowStr,
            sector: sid,
            kind: "ALERT",
            text: `FAIL-SAFE: ESP32-${sid} lost RPi 5 contact → auto-closed local valve.`,
          });
        }
        continue;
      }

      onlineCount += 1;
      sec.node.node_online = true;
      sec.node.last_seen_ago = 0;

      // Apply per-sensor faults
      const sh = sec.sensor_health;
      const reading = {
        moisture: Number(phys.moisture.toFixed(2)),
        temperature: Number(phys.temperature.toFixed(2)),
        humidity: Number(phys.humidity.toFixed(2)),
        light_lux: Math.round(phys.light_lux),
        flow: effFlow,
      };
      const chErrors = {};
      const bad = { moisture: 148, temperature: -45, humidity: -12, light_lux: -500, flow: -9.9 };
      const frozenKey = (k) => `${sid}_${k}`;

      for (const ch of ["moisture", "temperature", "humidity", "light_lux", "flow"]) {
        const fMode = sh[ch] || "ok";
        if (fMode === "missing") {
          reading[ch] = null;
          chErrors[ch] = `missing '${ch}'`;
        } else if (fMode === "invalid") {
          reading[ch] = bad[ch];
          chErrors[ch] = `'${ch}' out of range (${bad[ch]})`;
        } else if (fMode === "stale") {
          if (!(frozenKey(ch) in sb._frozen)) sb._frozen[frozenKey(ch)] = reading[ch];
          reading[ch] = sb._frozen[frozenKey(ch)];
          chErrors[ch] = `'${ch}' frozen/stale`;
        } else if (fMode === "noisy") {
          reading[ch] = Number((reading[ch] + (Math.random() - 0.5) * 28).toFixed(2));
        } else {
          delete sb._frozen[frozenKey(ch)];
        }
      }

      sec.sensor.sequence_number += 1;
      sec.sensor.moisture = reading.moisture;
      sec.sensor.temperature = reading.temperature;
      sec.sensor.humidity = reading.humidity;
      sec.sensor.light_lux = reading.light_lux;
      sec.sensor.flow_rate_lpm = reading.flow;
      sec.valve.flow_rate_lpm = reading.flow ?? 0;
      sec.channel_errors = chErrors;

      const anyStale = Object.values(sh).some((v) => v === "stale");
      const anyErr = Object.keys(chErrors).length > 0;
      sec.node.status = anyErr || anyStale ? "stale" : "online";
      sec.node.reading_valid = !chErrors.moisture;
      sec.node.invalid_reason = Object.values(chErrors).join("; ");

      this._bumpActivity("sensors");
      this.onPacket(sid, "telemetry");
      this.onLog({
        time: nowStr,
        sector: sid,
        kind: "SENSORS",
        text: `farm/sector${sid}/sensors → M:${reading.moisture ?? "NULL"}% T:${reading.temperature ?? "NULL"}°C H:${reading.humidity ?? "NULL"}% Flow:${reading.flow ?? "NULL"}`,
      });

      // Push chart history point
      this.history[sid].push({
        moisture: reading.moisture,
        temperature: reading.temperature,
        humidity: reading.humidity,
        flow: reading.flow,
        timestamp: new Date().toISOString(),
      });
      if (this.history[sid].length > 45) this.history[sid].shift();

      // RPi 5 Rule Engine Reaction!
      const alerts = [];
      if (!chErrors.flow) {
        if (sec.valve.state === "OPEN" && reading.flow <= 0.01) {
          alerts.push("zero_flow_fault");
          this._bumpActivity("alerts");
          this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `RPi 5: Sector ${sid} valve OPEN but Flow=0 L/min (Pump/Supply Failure!)` });
        } else if (sec.valve.state === "CLOSED" && reading.flow > 0.1) {
          alerts.push("valve_leak_detected");
          this._bumpActivity("alerts");
          this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `RPi 5: Sector ${sid} LEAK detected (${reading.flow} L/min while CLOSED!)` });
        }
      }

      if (chErrors.moisture) {
        sec.last_decision = {
          action: "SAFETY_LOCK",
          reason: `Moisture sensor fault (${chErrors.moisture}) — RPi 5 locked AUTO watering safe!`,
          alerts: [...alerts, "moisture_sensor_fault"],
        };
        if (sec.mode === "AUTO" && sec.valve.state === "OPEN") {
          this._executeSandboxCommand(sid, "CLOSE", "rpi5_safety");
        }
      } else if (sec.mode === "AUTO") {
        const th = sb.thresholds;
        if (reading.temperature !== null && reading.temperature > th.temp_alert) alerts.push("high_temperature");
        if (reading.temperature !== null && reading.temperature <= 3.0) alerts.push("frost_risk");
        if (reading.humidity !== null && reading.humidity < th.humidity_alert) alerts.push("low_humidity");

        let action = "MAINTAIN";
        let reason = `Moisture ${reading.moisture.toFixed(1)}% in hysteresis band (${th.moisture_start}–${th.moisture_stop}%). Holding ${sec.valve.state}.`;
        if (reading.moisture < th.moisture_start) {
          action = "OPEN";
          reason = `Moisture ${reading.moisture.toFixed(1)}% < ${th.moisture_start}% start threshold → OPEN valve.`;
        } else if (reading.moisture > th.moisture_stop) {
          action = "CLOSE";
          reason = `Moisture ${reading.moisture.toFixed(1)}% > ${th.moisture_stop}% stop threshold → CLOSE valve.`;
        }
        sec.last_decision = { action, reason, alerts };

        if (action === "OPEN" && sec.valve.state === "CLOSED") {
          this._executeSandboxCommand(sid, "OPEN", "rpi5_master");
        } else if (action === "CLOSE" && sec.valve.state === "OPEN") {
          this._executeSandboxCommand(sid, "CLOSE", "rpi5_master");
        }
      }

      if (sec.valve.state === "OPEN") openValves += 1;
    }

    sb.online_node_count = onlineCount;
    sb.active_valve_count = openValves;
    sb.total_water_consumed_litres = Number(totalWater.toFixed(3));
    if (this.activityBuckets.length === 0 && this.currentBucket.total > 0) {
      this.activityBuckets.push({ ...this.currentBucket });
    }
    this.onUpdate(sb, this.mode, null);
  }

  _executeSandboxCommand(sid, action, source) {
    const sec = this.sandbox.sectors[String(sid)];
    const nowStr = new Date().toTimeString().slice(0, 8);
    const vMode = sec.valve.fault_mode;
    sec.valve.desired_state = action === "OPEN" ? "OPEN" : "CLOSED";

    this._bumpActivity("commands");
    this.onPacket(sid, "command");
    this.onLog({
      time: nowStr,
      sector: sid,
      kind: "COMMAND",
      text: `RPi 5 → farm/sector${sid}/command: ${action} (${source})`,
    });

    setTimeout(() => {
      if (sec.node.disconnected || this.sandbox.crisis === "broker_outage") return;
      if (vMode === "no_ack") {
        this._bumpActivity("alerts");
        this.onPacket(sid, "alert");
        this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `ACK TIMEOUT: ESP32-${sid} failed to acknowledge ${action}!` });
        return;
      }
      if (action === "OPEN" && vMode === "stuck_closed") {
        this._bumpActivity("alerts");
        this.onPacket(sid, "alert");
        this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `VALVE FAULT: Sector ${sid} valve STUCK CLOSED — refused OPEN!` });
        return;
      }
      if ((action === "CLOSE" || action === "EMERGENCY_OFF") && vMode === "stuck_open") {
        this._bumpActivity("alerts");
        this.onPacket(sid, "alert");
        this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `VALVE FAULT: Sector ${sid} valve STUCK OPEN — failed to close!` });
        return;
      }
      sec.valve.state = action === "OPEN" ? "OPEN" : "CLOSED";
      this._bumpActivity("acks");
      this.onPacket(sid, "telemetry");
      this.onLog({ time: nowStr, sector: sid, kind: "ACK", text: `ESP32-${sid} ACK ACCEPTED → Valve ${sec.valve.state}` });
    }, 320);
  }

  // ── PUBLIC CONTROL ACTIONS (dispatches to backend OR sandbox) ──

  async _post(url, data) {
    if (this.mode === "backend") {
      try {
        await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
      } catch {}
    }
  }

  async sendCommand(sectorId, action) {
    if (this.mode === "backend") return this._post("/api/command", { sector_id: sectorId, action });
    if (action === "EMERGENCY_OFF") {
      for (const s of [1, 2, 3, 4]) this._executeSandboxCommand(s, "EMERGENCY_OFF", "emergency");
    } else {
      this._executeSandboxCommand(sectorId, action, "manual_user");
    }
  }

  async setMode(sectorId, mode) {
    if (this.mode === "backend") return this._post("/api/mode", { sector_id: sectorId, mode });
    this.sandbox.sectors[String(sectorId)].mode = mode;
    this._tickSandbox();
  }

  async setSensorFault(sectorId, sensor, mode) {
    if (this.mode === "backend") return this._post("/api/sensor_fault", { sector_id: sectorId, sensor, mode });
    this.sandbox.sectors[String(sectorId)].sensor_health[sensor] = mode;
    this._tickSandbox();
  }

  async setValveFault(sectorId, mode) {
    if (this.mode === "backend") return this._post("/api/valve_fault", { sector_id: sectorId, mode });
    this.sandbox.sectors[String(sectorId)].valve.fault_mode = mode;
    this._tickSandbox();
  }

  async toggleDisconnect(sectorId, disconnect) {
    if (this.mode === "backend") return this._post("/api/node_disconnect", { sector_id: sectorId, disconnect });
    this.sandbox.sectors[String(sectorId)].node.disconnected = disconnect;
    this._tickSandbox();
  }

  async setCrisis(crisis) {
    if (this.mode === "backend") return this._post("/api/crisis", { crisis });
    const sb = this.sandbox;
    const prev = sb.crisis;
    if (crisis === prev) return;
    sb.crisis = crisis;
    const nowStr = new Date().toTimeString().slice(0, 8);
    const th = sb.thresholds;

    for (const sid of [1, 2, 3, 4]) {
      const phys = sb._phys[sid];
      const sec = sb.sectors[String(sid)];
      if (crisis === "heatwave") {
        phys.temperature = Math.max(phys.temperature + 8.5, 40.0);
        phys.humidity = Math.min(phys.humidity - 16, 21);
        phys.light_lux = 78000;
        phys.moisture = Math.max(5, phys.moisture - 9);
        this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `ESP32-${sid} heatwave surge (${phys.temperature.toFixed(1)}°C) → immediate cooling check.` });
        if (sec.mode === "AUTO" && sec.valve.state === "CLOSED" && sec.sensor_health.moisture === "ok" && phys.moisture < th.moisture_start + 5) {
          this._executeSandboxCommand(sid, "OPEN", "esp32_heatwave");
        }
      } else if (crisis === "rainstorm") {
        phys.moisture = Math.min(100, phys.moisture + 16);
        phys.temperature = Math.min(phys.temperature, 21.5);
        phys.humidity = Math.max(phys.humidity, 94);
        phys.light_lux = 4400;
        this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `ESP32-${sid} DHT22/soil rain deluge detected → immediate shutoff.` });
        if (sec.mode === "AUTO" && sec.valve.state === "OPEN") {
          this._executeSandboxCommand(sid, "CLOSE", "esp32_rain_shutoff");
        }
      } else if (crisis === "frost") {
        phys.temperature = 1.4;
        phys.humidity = Math.max(phys.humidity, 84);
        phys.light_lux = 12000;
        this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `FROST RISK: ESP32-${sid} temp ${phys.temperature.toFixed(1)}°C ≤ 3°C → locking valve CLOSED!` });
        if (sec.valve.state === "OPEN") {
          this._executeSandboxCommand(sid, "CLOSE", "esp32_frost_protect");
        }
      } else if (crisis === "water_supply_failure") {
        this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `PUMP FAILURE: ESP32-${sid} flow 0.0 L/m → protecting solenoid.` });
        if (sec.valve.state === "OPEN") {
          this._executeSandboxCommand(sid, "CLOSE", "esp32_dryrun_shutoff");
        }
      } else if (crisis === "broker_outage") {
        if (sec.valve.state === "OPEN") sec.valve.state = "CLOSED";
        this.onLog({ time: nowStr, sector: sid, kind: "ALERT", text: `BROKER OUTAGE: ESP32-${sid} engaged immediate local fail-safe (valve CLOSED).` });
      } else if (crisis === "normal" && prev !== "normal") {
        phys.temperature = INITIAL_SECTORS[sid].temperature;
        phys.humidity = INITIAL_SECTORS[sid].humidity;
        phys.light_lux = INITIAL_SECTORS[sid].light_lux;
      }
    }
    this._tickSandbox();
  }

  async applyManualSensor(sectorId, moisture, temperature, humidity) {
    if (this.mode === "backend") {
      return this._post("/api/manual_sensor", { sector_id: sectorId, moisture, temperature, humidity });
    }
    Object.assign(this.sandbox._phys[sectorId], { moisture, temperature, humidity });
    this._tickSandbox();
  }

  async saveThresholds(th) {
    if (this.mode === "backend") return this._post("/api/thresholds", th);
    this.sandbox.thresholds = {
      moisture_start: th.moisture_start,
      moisture_stop: th.moisture_stop,
      temp_alert: th.temp_alert,
      humidity_alert: th.humidity_alert,
    };
    this.sandbox.flow_rate_lpm = th.flow_rate_lpm;
    this._tickSandbox();
  }

  async restoreAll() {
    if (this.mode === "backend") return this._post("/api/restore_all", {});
    this.sandbox.crisis = "normal";
    for (const s of [1, 2, 3, 4]) {
      const sec = this.sandbox.sectors[String(s)];
      sec.node.disconnected = false;
      sec.valve.fault_mode = "normal";
      for (const k of Object.keys(sec.sensor_health)) sec.sensor_health[k] = "ok";
    }
    this._tickSandbox();
  }
}
