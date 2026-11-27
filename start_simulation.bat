@echo off
cd /d "%~dp0"

echo ============================================================
echo   Virtual Smart Agriculture Irrigation System - Startup
echo ============================================================

REM --- 1. Check / Start Mosquitto MQTT Broker ---
netstat -an | findstr ":1883 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% == 0 (
    echo [OK] Mosquitto MQTT broker is already running on port 1883.
    goto :broker_ready
)

set "MOSQUITTO_EXE="
if exist "C:\Program Files\mosquitto\mosquitto.exe" (
    set "MOSQUITTO_EXE=C:\Program Files\mosquitto\mosquitto.exe"
) else (
    where mosquitto >nul 2>&1
    if %errorlevel% == 0 (
        set "MOSQUITTO_EXE=mosquitto"
    ) else (
        echo [ERROR] Mosquitto MQTT broker not found.
        echo         Install it from https://mosquitto.org/download/
        pause
        exit /b 1
    )
)
echo [INFO] Starting MQTT Broker...
start "MQTT Broker" cmd /k ""%MOSQUITTO_EXE%" -v"
echo [INFO] Waiting 3 seconds for MQTT broker to start...
ping -n 4 127.0.0.1 >nul

:broker_ready

REM --- 2. Create required directories ---
if not exist "logs\" mkdir logs
if not exist "data\" mkdir data

REM --- 3. Locate Python (prefer venv if present) ---
set "PY_CMD=python"
if exist "venv\Scripts\python.exe" (
    set "PY_CMD=venv\Scripts\python.exe"
    echo [OK] Using virtual environment: venv\Scripts\python.exe
) else (
    echo [WARN] venv not found. Using system Python.
)

REM --- 4. Start Master Controller ---
echo [INFO] Starting Master Controller...
start "Master Controller" /D "%~dp0" cmd /k %PY_CMD% master\raspberry_pi_master.py
ping -n 3 127.0.0.1 >nul

REM --- 5. Start all four ESP32 Node Simulators ---
echo [INFO] Starting ESP32 Sector 1-4 nodes...
start "ESP32 Sector 1" /D "%~dp0" cmd /k %PY_CMD% esp32_nodes\esp32_sector_1.py
start "ESP32 Sector 2" /D "%~dp0" cmd /k %PY_CMD% esp32_nodes\esp32_sector_2.py
start "ESP32 Sector 3" /D "%~dp0" cmd /k %PY_CMD% esp32_nodes\esp32_sector_3.py
start "ESP32 Sector 4" /D "%~dp0" cmd /k %PY_CMD% esp32_nodes\esp32_sector_4.py
ping -n 4 127.0.0.1 >nul

REM --- 6. Start Streamlit Dashboard ---
echo [INFO] Starting Dashboard on http://localhost:8501 ...
start "Dashboard" /D "%~dp0" cmd /k %PY_CMD% -m streamlit run dashboard\app.py --server.port 8501 --server.headless true

echo.
echo ============================================================
echo   System started! Dashboard at http://localhost:8501
echo ============================================================
echo   To stop everything cleanly, run: stop_simulation.bat
echo ============================================================