# 🌱 Virtual Smart Agriculture Irrigation System

A fully simulated, end-to-end smart irrigation platform that demonstrates how IoT edge nodes (ESP32), an MQTT message broker, a central controller (Raspberry Pi), and a real-time web dashboard would work together to automatically water crops based on soil-moisture sensors.

> **No real hardware required.** Everything — soil sensors, valves, network delays, and hardware faults — is simulated in Python.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Running the System](#running-the-system)
5. [Project Structure](#project-structure)
6. [MQTT Topic Schema](#mqtt-topic-schema)
7. [Decision Engine Rules](#decision-engine-rules)
8. [Acceptance Test Checklist](#acceptance-test-checklist)
9. [Troubleshooting](#troubleshooting)
10. [Stopping the System](#stopping-the-system)
11. [What Would Change with Real Hardware](#what-would-change-with-real-hardware)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Farm Network                             │
│                                                                 │
│  ┌──────────────┐   MQTT publish    ┌────────────────────────┐  │
│  │ ESP32 Sec. 1 │──────────────────▶│                        │  │
│  └──────────────┘  farm/sector1/   │                        │  │
│                     telemetry      │   Mosquitto MQTT       │  │
│  ┌──────────────┐                  │   Broker               │  │
│  │ ESP32 Sec. 2 │──────────────────▶   localhost:1883       │  │
│  └──────────────┘                  │                        │  │
│                                    │                        │  │
│  ┌──────────────┐                  │                        │◀─┤──subscribe
│  │ ESP32 Sec. 3 │──────────────────▶                        │  │  farm/sector+/
│  └──────────────┘                  └───────────┬────────────┘  │  telemetry
│                                                │               │
│  ┌──────────────┐                   publish    │  subscribe    │
│  │ ESP32 Sec. 4 │──────────────────▶ farm/     │  farm/        │
│  └──────────────┘  MQTT subscribe   system/*   │  sector+/*    │
│         ▲          farm/sectorN/               ▼               │
│         │          command          ┌────────────────────────┐  │
│         │                          │  Raspberry Pi Master   │  │
│         └──────────────────────────│  (Decision Engine +    │  │
│              valve commands        │   Data Logger)         │  │
│                                    └───────────┬────────────┘  │
│                                                │               │
│                                     writes     │  reads        │
│                                    JSON/SQLite  │               │
│                                                ▼               │
│                                    ┌────────────────────────┐  │
│                                    │  Streamlit Dashboard   │  │
│                                    │  http://localhost:8501 │  │
│                                    └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Data flow summary:**

1. **ESP32 nodes** publish sensor readings (moisture, temperature, humidity, light) every 5 seconds.
2. **MQTT Broker** routes all messages between components.
3. **Master Controller** subscribes to telemetry, runs the decision engine, opens/closes valves, logs everything to SQLite, and writes a live JSON state file.
4. **Dashboard** reads the JSON state file + SQLite database and displays metrics, charts, and alerts. It can also publish manual valve commands back through MQTT.

---

## Prerequisites

| Requirement | Version | Download |
|---|---|---|
| Python | 3.9 or newer | https://www.python.org/downloads/ |
| Mosquitto MQTT Broker | 2.0+ | https://mosquitto.org/download/ |
| Operating System | Windows 10 / 11 | — |

> **Note:** The simulation runs entirely on one Windows PC. No network hardware is needed.

---

## Installation

Follow these steps **exactly**, in order.

### Step 1 — Install Python

1. Go to https://www.python.org/downloads/
2. Download the **Windows installer** (Python 3.11 or 3.12 recommended).
3. Run the installer. **Important:** tick **"Add Python to PATH"** before clicking Install.
4. Open a new Command Prompt and confirm:
   ```
   python --version
   ```
   You should see something like `Python 3.11.9`.

### Step 2 — Install Mosquitto MQTT Broker

1. Go to https://mosquitto.org/download/
2. Download the **Windows installer** (`.exe`).
3. Run the installer. Leave all defaults; note the install path (usually `C:\Program Files\mosquitto\`).
4. *(Optional — for Windows Service)* Open a Command Prompt **as Administrator** and run:
   ```
   net start mosquitto
   ```
   The simulation launcher will start Mosquitto for you, so this step is optional.
5. Confirm it works:
   ```
   "C:\Program Files\mosquitto\mosquitto.exe" --version
   ```

### Step 3 — Get the Project

If you received a ZIP file, extract it. If cloning from Git:
```
git clone <repository-url>
cd smart_agriculture
```

### Step 4 — Open a Command Prompt in the Project Folder

In File Explorer, navigate to the `smart_agriculture` folder. Click in the address bar, type `cmd`, and press Enter.

### Step 5 — Create a Virtual Environment

```cmd
python -m venv venv
```

This creates a `venv\` folder with an isolated Python environment.

### Step 6 — Activate the Virtual Environment

```cmd
venv\Scripts\activate
```

Your prompt will change to show `(venv)` at the start, confirming it is active.

### Step 7 — Install Python Dependencies

```cmd
pip install -r requirements.txt
```

This installs paho-mqtt, Streamlit, pandas, plotly, and requests. It may take a minute or two.

---

## Running the System

Once installed, starting the full system is a single step:

**Double-click `start_simulation.bat`**

(Or from your cmd prompt: `start_simulation.bat`)

This will open **7 separate windows**:

| Window Title | What it does |
|---|---|
| MQTT Broker | Runs the Mosquitto message broker |
| Master Controller | Runs the decision engine and data logger |
| ESP32 Sector 1 | Simulates soil sensor + valve node for Sector 1 |
| ESP32 Sector 2 | Simulates soil sensor + valve node for Sector 2 |
| ESP32 Sector 3 | Simulates soil sensor + valve node for Sector 3 |
| ESP32 Sector 4 | Simulates soil sensor + valve node for Sector 4 |
| Dashboard | Runs the Streamlit web UI |

After about 5–10 seconds, open your browser and go to:

**http://localhost:8501**

---

## Project Structure

```
smart_agriculture\
│
├── start_simulation.bat        ← Double-click to start everything
├── stop_simulation.bat         ← Double-click to stop everything
├── requirements.txt            ← Python dependencies
│
├── .streamlit\
│   └── config.toml             ← Headless Streamlit & port 8501 config
│
├── config\
│   └── settings.json           ← All tunable parameters (thresholds, MQTT config, sector definitions)
│
├── simulation\
│   ├── sensor_simulator.py     ← Generates realistic, drifting sensor readings per sector
│   ├── irrigation_model.py     ← Tracks valve states and water consumption
│   └── fault_simulator.py      ← Injects faults (stale data, disconnects, valve failures)
│
├── master\
│   ├── raspberry_pi_master.py  ← Central controller: subscribes to sensors/status, runs decision engine,
│   │                              publishes valve commands, logs to SQLite, writes JSON state
│   ├── decision_engine.py      ← Transparent rule-based ('fake AI') irrigation decision engine
│   ├── mqtt_manager.py         ← Resilient Paho-MQTT wrapper with exponential backoff
│   └── database.py             ← SQLite persistence for readings, commands, ACKs, alerts, events
│
├── esp32_nodes\
│   ├── base_node.py            ← Shared virtual ESP32 node runtime (MQTT, fail-safe, valve control)
│   ├── esp32_sector_1.py       ← Simulated ESP32 process for Sector 1
│   ├── esp32_sector_2.py       ← Simulated ESP32 process for Sector 2
│   ├── esp32_sector_3.py       ← Simulated ESP32 process for Sector 3
│   └── esp32_sector_4.py       ← Simulated ESP32 process for Sector 4
│
├── dashboard\
│   └── app.py                  ← Streamlit web dashboard (live metrics, charts, manual control)
│
├── data\                       ← Created automatically at startup
│   ├── system_state.json       ← Live JSON state written by master every 5 seconds
│   └── farm_history.db         ← SQLite database: all telemetry, commands, alerts, events
│
└── logs\                       ← Created automatically at startup
    └── system.log              ← Rotating log file from master controller
```

---

## MQTT Topic Schema

All topics are under the `farm/` namespace.

| Topic | Direction | Publisher | Subscriber | Payload (JSON) | Description |
|---|---|---|---|---|---|
| `farm/sector1/sensors` | → Broker | ESP32 Sec. 1 | Master | `{sector_id, node_id, moisture, temperature, humidity, light_lux, timestamp, sequence_number, valve_state, flow_rate_lpm, water_consumed_litres}` | Sensor readings, every 5 s |
| `farm/sector2/sensors` | → Broker | ESP32 Sec. 2 | Master | *(same schema)* | |
| `farm/sector3/sensors` | → Broker | ESP32 Sec. 3 | Master | *(same schema)* | |
| `farm/sector4/sensors` | → Broker | ESP32 Sec. 4 | Master | *(same schema)* | |
| `farm/sector1/command` | ← Broker | Master / Dashboard | ESP32 Sec. 1 | `{cmd_id, action, sector_id, timestamp, source}` | Valve commands (`OPEN`/`CLOSE`/`EMERGENCY_OFF`) |
| `farm/sector2/command` | ← Broker | Master / Dashboard | ESP32 Sec. 2 | *(same schema)* | |
| `farm/sector3/command` | ← Broker | Master / Dashboard | ESP32 Sec. 3 | *(same schema)* | |
| `farm/sector4/command` | ← Broker | Master / Dashboard | ESP32 Sec. 4 | *(same schema)* | |
| `farm/sector1/status` | → Broker | ESP32 Sec. 1 | Master | `{cmd_id, sector_id, node_id, status, valve_state, flow_rate_lpm, water_consumed_litres, timestamp, reason}` | Command ACKs (`ACCEPTED`/`REJECTED`) & node status |
| `farm/sector2/status` | → Broker | ESP32 Sec. 2 | Master | *(same schema)* | |
| `farm/sector3/status` | → Broker | ESP32 Sec. 3 | Master | *(same schema)* | |
| `farm/sector4/status` | → Broker | ESP32 Sec. 4 | Master | *(same schema)* | |
| `farm/system/alerts` | → Broker | Master / Nodes | Master & Dashboard | `{sector_id, alert_type, message, severity, timestamp}` | System-level alerts |
| `farm/system/status` | → Broker | Master | ESP32 Nodes & Dashboard | `{master_id, master_online, broker_connected, online_node_count, active_valve_count, total_water_consumed_litres, timestamp}` | Master heartbeat |
| `farm/system/config` | ← Broker | Dashboard | Master & ESP32 Nodes | `{cmd_id, settings, timestamp, source}` | Settings update from UI |
| `farm/system/control` | ← Broker | Dashboard | Master | `{cmd_id, action, sector_id, mode, timestamp, source}` | Mode switch (`AUTO`/`MANUAL`) & emergency control |

---

## Decision Engine Rules

The master controller evaluates these rules **in priority order** every time a new telemetry message arrives:

| Priority | Rule Name | Condition | Action |
|---|---|---|---|
| 1 | **Failsafe Timeout** | Valve has been OPEN for ≥ 90 seconds with no ACK | Force CLOSE valve; raise CRITICAL alert |
| 2 | **Node Offline** | No telemetry received from a node for ≥ 60 seconds | Raise WARNING alert; close valve if open |
| 3 | **Stale Data** | Consecutive identical readings for ≥ 30 seconds | Raise WARNING; flag data as suspect |
| 4 | **Invalid Data** | Reading out of valid range (moisture 0–100, temp −10–60, humidity 0–100) | Discard reading; raise WARNING alert |
| 5 | **High Temperature Alert** | Temperature ≥ 35 °C | Raise INFO alert (consider extra watering) |
| 6 | **Low Humidity Alert** | Humidity ≤ 35 % | Raise INFO alert |
| 7 | **Auto Open Valve** | Moisture < 30 % AND valve CLOSED AND mode = AUTO | Publish OPEN command to sector |
| 8 | **Auto Close Valve** | Moisture ≥ 55 % AND valve OPEN AND mode = AUTO | Publish CLOSE command to sector |
| 9 | **ACK Timeout** | Command sent but no ACK received within 10 seconds | Retry command (up to 3 times); raise WARNING |
| 10 | **Manual Override** | Dashboard sets mode = MANUAL | Disable auto rules 7 & 8 for that sector |

---

## Acceptance Test Checklist

Use this list to verify the system is working correctly after installation.

| # | Test | Expected Result | ✓ |
|---|---|---|---|
| 1 | Start `start_simulation.bat` | All 7 windows open; no errors in any window | ☐ |
| 2 | Open http://localhost:8501 | Dashboard loads within 15 seconds | ☐ |
| 3 | Sector 1 overview card | Shows live moisture, temperature, humidity values | ☐ |
| 4 | Sector 2 valve status | Shows CLOSED (initial moisture 68 % — above threshold) | ☐ |
| 5 | Sector 1 valve status | Shows OPEN within ~10 s (initial moisture 22 % — below threshold) | ☐ |
| 6 | Sector 4 valve status | Shows OPEN within ~10 s (initial moisture 18 % — below threshold) | ☐ |
| 7 | Live Charts page | Moisture chart updates and shows all 4 sectors | ☐ |
| 8 | Event Log page | Shows valve OPEN/CLOSE commands and ACK entries | ☐ |
| 9 | Manual override — Sector 1 | Switch to MANUAL, click CLOSE → valve closes; master does not auto-reopen | ☐ |
| 10 | Fault Injection — Stale Data | Click "Inject Stale Data" for Sector 3 → WARNING alert appears on dashboard | ☐ |
| 11 | Fault Injection — Disconnect | Click "Simulate Disconnect" for Sector 2 → node shown OFFLINE in red | ☐ |
| 12 | Restore All faults | Click "Restore All" → nodes recover; sensor values resume updating | ☐ |
| 13 | Settings page | Change moisture_start to 25, click Save → master uses new threshold | ☐ |
| 14 | Stop `stop_simulation.bat` | All windows close; no python.exe or mosquitto.exe in Task Manager | ☐ |

---

## Troubleshooting

### Port 1883 already in use

**Symptom:** The MQTT Broker window shows `Error: Address already in use`.

**Fix:** Another Mosquitto instance is already running.

Option A — Stop the Windows service:
```cmd
net stop mosquitto
```
Then re-run `start_simulation.bat`.

Option B — Kill the existing process:
```cmd
taskkill /F /IM mosquitto.exe
```

---

### Python not found

**Symptom:** A window flashes and closes immediately, or you see `'python' is not recognized`.

**Fix:**
1. Confirm Python is installed: open Start → type `python` → click the Python app.
2. If it opens the Microsoft Store instead, Python is not installed — go back to [Step 1](#step-1--install-python).
3. After installing, close all Command Prompt windows and try again (the PATH only updates in new shells).

---

### MQTT Broker won't start

**Symptom:** Broker window shows `Error: Problem with configuration` or exits immediately.

**Fix 1:** A `mosquitto.conf` in `C:\Program Files\mosquitto\` may have invalid settings. Rename it to `mosquitto.conf.bak` and try again.

**Fix 2:** Check Windows Event Viewer → Windows Logs → Application for more detail.

**Fix 3:** Run Mosquitto manually in verbose mode to see the full error:
```cmd
"C:\Program Files\mosquitto\mosquitto.exe" -v
```

---

### Dashboard shows "Waiting for master..."

**Symptom:** Dashboard loads but shows no sensor data.

**Fix:** The master hasn't written `data/system_state.json` yet.
- Wait 10–15 seconds and refresh the page.
- Check the **Master Controller** window for error messages.
- Confirm the MQTT broker is running (the **MQTT Broker** window must be open).

---

### pip install fails with SSL or proxy errors

**Fix:** Try:
```cmd
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

---

## Stopping the System

**Double-click `stop_simulation.bat`**

This will:
1. Kill all `python.exe` processes (closes all ESP32, master, and dashboard windows).
2. Kill `mosquitto.exe` (closes the broker).
3. Print "Simulation stopped."

> **Note:** This kills **all** Python processes on your machine. If you have other Python programs running (Jupyter, another script), save their work first.

---

## What Would Change with Real Hardware

This project simulates the full system in software. Here is what changes when you deploy to real hardware:

| Aspect | Simulated (this project) | Real Hardware |
|---|---|---|
| **ESP32 nodes** | Python scripts on the same PC | Physical ESP32 microcontrollers, each connected to soil-moisture sensors, DHT22 (temp/humidity), LDR (light), and a relay controlling a solenoid valve |
| **Sensor readings** | Gaussian noise added to initial values in `sensor_simulator.py` | Readings from ADC pins on the ESP32 (e.g., capacitive soil-moisture sensor on GPIO34) |
| **Valve open/close** | `irrigation_model.py` sets a flag in memory | GPIO output pin on ESP32 activates a relay module that switches 12 V to the solenoid valve |
| **MQTT transport** | Loopback on localhost (127.0.0.1) | Wi-Fi (ESP32's built-in Wi-Fi connects to local router; Raspberry Pi on same network) |
| **Master controller** | Python script on the same PC | Python script running on a Raspberry Pi 4 (always-on, low power) |
| **Water consumption** | Calculated from flow_rate × time in `irrigation_model.py` | Measured by a YF-S201 flow meter on the water line, publishing real litres |
| **Power** | None (all software) | ESP32 nodes powered by 5 V USB or solar + LiPo battery; RPi on mains or solar |
| **Fault detection** | Injected programmatically via dashboard buttons | Real-world: sensor disconnected, power failure, water pressure drop, pipe burst |
| **Latency** | Near-zero (loopback) | Real Wi-Fi latency (5–50 ms typical); matters for valve ACK timeout tuning |
| **Security** | No authentication (local only) | TLS on MQTT (port 8883), username/password, certificate pinning on ESP32 |
| **OTA updates** | Not needed | ESP-IDF OTA partition or ArduinoOTA to update ESP32 firmware over Wi-Fi |
| **Dashboard access** | localhost only | Exposed on local network or via reverse proxy (nginx + Let's Encrypt) |

The code architecture (MQTT topics, JSON payload schemas, decision-engine logic, database schema) is designed to be identical in both modes — only the I/O layer changes.
