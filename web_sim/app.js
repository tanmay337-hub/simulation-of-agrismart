import { Farm3DScene } from "./farm3d.js";
import { SimController } from "./sim_engine.js";
import { drawLineChart, drawActivityBars } from "./charts.js";

const SENSOR_META = [
  { key: "moisture",    name: "Soil Moisture Probe",  pin: "GPIO 34 · Capacitive ADC", unit: "%" },
  { key: "temperature", name: "Temperature Sensor",   pin: "GPIO 4 · DHT22",           unit: "°C" },
  { key: "humidity",    name: "Humidity Sensor",      pin: "GPIO 4 · DHT22",           unit: "%" },
  { key: "light_lux",   name: "Light Intensity",      pin: "I2C 0x23 · BH1750",        unit: " lux" },
  { key: "flow",        name: "Water Flow Meter",     pin: "GPIO 27 · YF-S201 Pulse",  unit: " L/m" },
];

const CRISIS_LABELS = {
  normal: "NORMAL SUNNY DAY",
  heatwave: "🔥 HEATWAVE & DROUGHT CRISIS",
  rainstorm: "🌧️ HEAVY MONSOON RAINSTORM",
  frost: "❄️ FROST COLD SNAP",
  water_supply_failure: "🚱 MAIN PUMP / WATER FAILURE",
  broker_outage: "📡 MQTT BROKER OUTAGE",
};

const SECTOR_TITLES = {
  1: "ESP32_SECTOR_1 (Tomatoes)",
  2: "ESP32_SECTOR_2 (Wheat)",
  3: "ESP32_SECTOR_3 (Corn)",
  4: "ESP32_SECTOR_4 (Soybeans)",
};

let selectedSector = 1;
let latestState = null;
const logs = [];

// DOM refs
const elDot = document.getElementById("backend-dot");
const elBackendLbl = document.getElementById("backend-label");
const elKpiNodes = document.getElementById("kpi-nodes");
const elKpiValves = document.getElementById("kpi-valves");
const elKpiWater = document.getElementById("kpi-water");
const elCrisisBadge = document.getElementById("active-crisis-badge");
const elCrisis3DBanner = document.getElementById("crisis-banner-3d");
const elHudTooltip = document.getElementById("hud-tooltip");
const elRpiBadge = document.getElementById("rpi-status-badge");
const elRpiReactions = document.getElementById("rpi-reactions");
const elSensorsList = document.getElementById("sensors-list");
const elLogFeed = document.getElementById("log-feed");

// 1. Three.js 3D Farmland
const farm3d = new Farm3DScene(
  document.getElementById("farm3d-canvas"),
  (sid) => selectSector(sid),
  (sid, label) => {
    if (elHudTooltip) elHudTooltip.textContent = `Inspecting ${label} — click to select`;
  }
);

// 2. Anime.js helper: MQTT packet blip across Off-Site RPi 5 wiring diagram
function animateWireBlip(direction = "up", kind = "telemetry") {
  if (!window.anime) return;
  const track = document.getElementById(direction === "down" ? "track-down" : "track-up");
  if (!track) return;
  const blip = document.createElement("div");
  blip.className = `mqtt-blip ${kind === "command" ? "cmd" : kind === "alert" ? "err" : ""}`;
  blip.style.left = direction === "down" ? "92%" : "0%";
  track.appendChild(blip);
  window.anime({
    targets: blip,
    left: direction === "down" ? ["92%", "0%"] : ["0%", "92%"],
    duration: 460,
    easing: "easeInOutQuad",
    complete: () => blip.remove(),
  });
}

function animateKpiPop(el) {
  if (!window.anime || !el) return;
  window.anime.remove(el);
  window.anime({ targets: el, scale: [1.14, 1], duration: 280, easing: "easeOutBack" });
}

// 3. Simulation Controller (Live MQTT backend + Browser fallback)
const sim = new SimController(
  (state, mode, simCtrl) => {
    latestState = state;
    renderUI(state, mode, simCtrl);
    farm3d.updateFromState(state);
    renderCharts();
  },
  (sid, kind) => {
    farm3d.spawnMqttPacket(sid, kind);
    animateWireBlip(kind === "command" ? "down" : "up", kind);
  },
  (item) => {
    logs.unshift(item);
    if (logs.length > 120) logs.pop();
    renderLogs();
  }
);

function selectSector(sid) {
  selectedSector = Number(sid);
  farm3d.setSelectedSector(selectedSector);
  document.querySelectorAll(".sec-tab").forEach((b) => {
    b.classList.toggle("active", Number(b.dataset.sector) === selectedSector);
  });
  if (latestState) {
    const s = latestState.sectors?.[String(selectedSector)]?.sensor || {};
    if (typeof s.moisture === "number") {
      slM.value = Math.round(s.moisture);
      document.getElementById("lbl-sl-m").textContent = `${slM.value}%`;
    }
    if (typeof s.temperature === "number") {
      slT.value = Math.round(s.temperature);
      document.getElementById("lbl-sl-t").textContent = `${slT.value}°C`;
    }
    if (typeof s.humidity === "number") {
      slH.value = Math.round(s.humidity);
      document.getElementById("lbl-sl-h").textContent = `${slH.value}%`;
    }
    renderInspector(latestState);
  }
}

function renderUI(state, mode) {
  // Backend mode pill
  if (mode === "backend") {
    elDot.className = "dot ok";
    elBackendLbl.textContent = "LIVE MQTT (4 ESP32 + RPi 5)";
  } else {
    elDot.className = "dot";
    elBackendLbl.textContent = "WEB SANDBOX (4 Virtual ESP32 + RPi 5)";
  }

  const nodesStr = `${state.online_node_count ?? 0} / 4`;
  const valvesStr = `${state.active_valve_count ?? 0} / 4`;
  const waterStr = `${Number(state.total_water_consumed_litres || 0).toFixed(2)} L`;
  if (elKpiNodes.textContent !== nodesStr) { elKpiNodes.textContent = nodesStr; animateKpiPop(elKpiNodes); }
  if (elKpiValves.textContent !== valvesStr) { elKpiValves.textContent = valvesStr; animateKpiPop(elKpiValves); }
  if (elKpiWater.textContent !== waterStr) { elKpiWater.textContent = waterStr; }

  // Crisis indicators
  const crisis = state.crisis || "normal";
  elCrisisBadge.textContent = CRISIS_LABELS[crisis] || crisis.toUpperCase();
  elCrisisBadge.classList.toggle("crisis-active", crisis !== "normal");
  document.querySelectorAll(".btn-chip").forEach((b) => {
    b.classList.toggle("active", b.dataset.crisis === crisis);
  });
  if (crisis !== "normal") {
    elCrisis3DBanner.classList.remove("hidden");
    elCrisis3DBanner.textContent = CRISIS_LABELS[crisis];
  } else {
    elCrisis3DBanner.classList.add("hidden");
  }

  // Off-Site RPi 5 Status & Per-Sector Reaction Cards
  const rpiOk = state.master_online && state.broker_connected;
  elRpiBadge.textContent = rpiOk ? "RPi 5: ONLINE (SAFE INDOORS)" : "RPi 5: LINK LOST";
  elRpiBadge.classList.toggle("offline", !rpiOk);

  elRpiReactions.innerHTML = [1, 2, 3, 4]
    .map((sid) => {
      const s = state.sectors?.[String(sid)] || {};
      const dec = s.last_decision || {};
      const v = s.valve || {};
      const hasFault = s.node?.status !== "online" || (v.fault_mode && v.fault_mode !== "normal") || Object.keys(s.channel_errors || {}).length > 0;
      const cls = hasFault ? "rpi-card fault" : v.state === "OPEN" ? "rpi-card irrig" : "rpi-card";
      return `
        <div class="${cls}" data-jump-sec="${sid}" style="cursor:pointer">
          <div class="rpi-card-head">
            <span>Sec ${sid} · ${dec.action || "WAIT"}</span>
            <span>Valve: ${v.state || "CLOSED"}</span>
          </div>
          <p>${dec.reason || "Awaiting telemetry..."}</p>
        </div>
      `;
    })
    .join("");

  elRpiReactions.querySelectorAll("[data-jump-sec]").forEach((el) => {
    el.onclick = () => selectSector(Number(el.dataset.jumpSec));
  });

  renderInspector(state);
}

function renderInspector(state) {
  const s = state.sectors?.[String(selectedSector)];
  if (!s) return;

  const node = s.node || {};
  const valve = s.valve || {};
  const sensor = s.sensor || {};
  const sh = s.sensor_health || {};
  const chErr = s.channel_errors || {};

  document.getElementById("sel-node-name").textContent = SECTOR_TITLES[selectedSector];
  document.getElementById("sensors-esp-label").textContent = `ESP32-${selectedSector}`;

  const pill = document.getElementById("sel-node-pill");
  const st = (node.status || "offline").toUpperCase();
  pill.textContent = st;
  pill.className = `pill ${st === "ONLINE" ? "" : st === "STALE" ? "stale" : "offline"}`;

  document.getElementById("sel-node-meta").textContent =
    `Seq #${sensor.sequence_number ?? 0} · Last packet: ${node.last_seen_ago ?? 0}s ago · Mode: ${s.mode}`;

  const btnDisc = document.getElementById("btn-toggle-node");
  const isDisc = Boolean(node.disconnected || st === "OFFLINE");
  btnDisc.textContent = isDisc ? "🔌 Reconnect ESP32" : "✂️ Disconnect ESP32";
  btnDisc.dataset.disconnected = String(isDisc);

  const btnMode = document.getElementById("btn-toggle-mode");
  btnMode.textContent = `Mode: ${s.mode}`;
  btnMode.className = `btn btn-sm ${s.mode === "MANUAL" ? "btn-amber" : ""}`;

  const manBar = document.getElementById("manual-valve-bar");
  manBar.classList.toggle("disabled", s.mode !== "MANUAL");

  // Render/update all 5 connected sensors WITHOUT destroying active <select> dropdowns
  const hasRows = elSensorsList.querySelectorAll(".sensor-row").length === SENSOR_META.length;
  if (!hasRows) {
    elSensorsList.innerHTML = SENSOR_META.map(
      (m) => `
      <div class="sensor-row" data-sensor-row="${m.key}">
        <div class="sensor-name">
          <strong>${m.name}</strong>
          <small data-pin="${m.key}">${m.pin}</small>
        </div>
        <div class="sensor-val" data-val="${m.key}">--</div>
        <select class="sensor-select" data-sensor="${m.key}">
          <option value="ok">✅ OK (Healthy)</option>
          <option value="missing">🕳️ Disconnected (NULL)</option>
          <option value="stale">🕰️ Frozen (Stale)</option>
          <option value="invalid">❌ Out-of-Range</option>
          <option value="noisy">⚡ Electrical Noise</option>
        </select>
      </div>`
    ).join("");

    elSensorsList.querySelectorAll(".sensor-select").forEach((sel) => {
      sel.onchange = () => {
        sim.setSensorFault(selectedSector, sel.dataset.sensor, sel.value);
      };
    });
  }

  for (const m of SENSOR_META) {
    const rawVal = m.key === "flow" ? (sensor.flow_rate_lpm ?? valve.flow_rate_lpm) : sensor[m.key];
    const fMode = sh[m.key] || "ok";
    const err = chErr[m.key];
    const isFault = fMode !== "ok" || Boolean(err);
    const valStr =
      rawVal === null || rawVal === undefined
        ? "NULL / MISSING"
        : `${Number(rawVal).toFixed(m.key === "light_lux" ? 0 : 1)}${m.unit}`;

    const row = elSensorsList.querySelector(`[data-sensor-row="${m.key}"]`);
    const pinEl = elSensorsList.querySelector(`[data-pin="${m.key}"]`);
    const valEl = elSensorsList.querySelector(`[data-val="${m.key}"]`);
    const selEl = elSensorsList.querySelector(`select[data-sensor="${m.key}"]`);
    if (row) row.classList.toggle("faulted", isFault);
    if (pinEl) pinEl.textContent = `${m.pin}${err ? " · " + err : ""}`;
    if (valEl) valEl.textContent = valStr;
    if (selEl && document.activeElement !== selEl) selEl.value = fMode;
  }

  document.getElementById("sel-valve-state").textContent = valve.state || "CLOSED";
  document.getElementById("sel-valve-desired").textContent = valve.desired_state || "CLOSED";
  document.getElementById("sel-valve-water").textContent = `${Number(valve.water_consumed_litres || 0).toFixed(2)} L`;

  const vSel = document.getElementById("sel-valve-fault");
  if (document.activeElement !== vSel) vSel.value = valve.fault_mode || "normal";
}

function renderCharts() {
  const th = latestState?.thresholds || { moisture_start: 30, moisture_stop: 55 };
  const flowMax = Math.max(5, Math.ceil(Number(latestState?.flow_rate_lpm || 2) * 1.5));
  const mMap = {};
  const tMap = {};
  const fMap = {};
  for (const sid of [1, 2, 3, 4]) {
    const arr = sim.history[sid] || [];
    mMap[sid] = arr.map((r) => r.moisture);
    tMap[sid] = arr.map((r) => r.temperature);
    fMap[sid] = arr.map((r) => r.flow_rate_lpm ?? r.flow ?? (latestState?.sectors?.[String(sid)]?.valve?.flow_rate_lpm ?? 0));
  }

  drawLineChart(document.getElementById("chart-moisture"), mMap, 0, 100, 25, [
    { value: Number(th.moisture_start || 30), color: "#c94a36", label: `Start ${th.moisture_start}%` },
    { value: Number(th.moisture_stop || 55), color: "#4f8a36", label: `Stop ${th.moisture_stop}%` },
  ]);
  drawLineChart(document.getElementById("chart-temp"), tMap, 0, 50, 10, [
    { value: Number(th.temp_alert || 35), color: "#c94a36", label: `Alert ${th.temp_alert}°C` },
  ]);
  drawLineChart(document.getElementById("chart-flow"), fMap, 0, flowMax, Math.max(1, Math.ceil(flowMax / 4)), []);
  drawActivityBars(document.getElementById("chart-activity"), sim.activityBuckets);
}

function renderLogs() {
  const sFilt = document.getElementById("log-filter-sector").value;
  const kFilt = document.getElementById("log-filter-kind").value;

  const filtered = logs.filter((l) => {
    if (sFilt !== "all" && String(l.sector) !== sFilt) return false;
    if (kFilt !== "all" && l.kind !== kFilt) return false;
    return true;
  });

  elLogFeed.innerHTML = filtered
    .slice(0, 60)
    .map(
      (l) => `
      <div class="log-item">
        <span style="color:#a89984">${l.time}</span>
        <span class="log-tag tag-${l.kind}">${l.kind}</span>
        <span>[Sec ${l.sector}] ${l.text}</span>
      </div>
    `
    )
    .join("");
}

// ── UI EVENT BINDINGS ──

document.querySelectorAll(".sec-tab").forEach((btn) => {
  btn.onclick = () => selectSector(Number(btn.dataset.sector));
});

document.querySelectorAll(".btn-mini[data-cam]").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".btn-mini[data-cam]").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    farm3d.focusCamera(btn.dataset.cam);
  };
});

document.querySelectorAll(".btn-chip[data-crisis]").forEach((btn) => {
  btn.onclick = () => {
    sim.setCrisis(btn.dataset.crisis);
    if (window.anime && btn.dataset.crisis !== "normal") {
      window.anime({ targets: ".crisis-bar", translateX: [-5, 5, -3, 3, 0], duration: 350, easing: "easeInOutSine" });
    }
  };
});

document.getElementById("btn-emergency").onclick = () => {
  sim.sendCommand(1, "EMERGENCY_OFF");
  if (window.anime) window.anime({ targets: "#btn-emergency", scale: [1.1, 1], duration: 300 });
};

document.getElementById("btn-restore-all").onclick = () => sim.restoreAll();

document.getElementById("btn-toggle-node").onclick = (e) => {
  const isDisc = e.currentTarget.dataset.disconnected === "true";
  sim.toggleDisconnect(selectedSector, !isDisc);
};

document.getElementById("btn-toggle-mode").onclick = () => {
  const cur = latestState?.sectors?.[String(selectedSector)]?.mode || "AUTO";
  sim.setMode(selectedSector, cur === "AUTO" ? "MANUAL" : "AUTO");
};

document.getElementById("btn-valve-open").onclick = () => sim.sendCommand(selectedSector, "OPEN");
document.getElementById("btn-valve-close").onclick = () => sim.sendCommand(selectedSector, "CLOSE");

document.getElementById("sel-valve-fault").onchange = (e) => {
  sim.setValveFault(selectedSector, e.target.value);
};

// Sliders
const slM = document.getElementById("sl-moisture");
const slT = document.getElementById("sl-temp");
const slH = document.getElementById("sl-humidity");
slM.oninput = () => (document.getElementById("lbl-sl-m").textContent = `${slM.value}%`);
slT.oninput = () => (document.getElementById("lbl-sl-t").textContent = `${slT.value}°C`);
slH.oninput = () => (document.getElementById("lbl-sl-h").textContent = `${slH.value}%`);
document.getElementById("btn-apply-sliders").onclick = () => {
  sim.applyManualSensor(selectedSector, Number(slM.value), Number(slT.value), Number(slH.value));
};

document.getElementById("btn-save-rules").onclick = () => {
  const mStart = Number(document.getElementById("in-start").value);
  const mStop = Number(document.getElementById("in-stop").value);
  if (mStart >= mStop) {
    alert("Start threshold must be strictly lower than Stop threshold.");
    return;
  }
  sim.saveThresholds({
    moisture_start: mStart,
    moisture_stop: mStop,
    temp_alert: Number(document.getElementById("in-temp").value),
    humidity_alert: Number(document.getElementById("in-hum").value),
    flow_rate_lpm: Number(document.getElementById("in-flow").value),
  });
};

document.getElementById("log-filter-sector").onchange = renderLogs;
document.getElementById("log-filter-kind").onchange = renderLogs;
