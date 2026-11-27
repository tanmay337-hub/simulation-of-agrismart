@echo off
echo ============================================================
echo   Virtual Smart Agriculture Irrigation System - Shutdown
echo ============================================================

echo [INFO] Stopping Smart Agriculture Python processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='streamlit.exe'\" | Where-Object { $_.CommandLine -match 'raspberry_pi_master|esp32_sector_|dashboard\\app\.py|smart_agriculture' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

echo [INFO] Closing simulation console windows...
taskkill /F /FI "WINDOWTITLE eq Master Controller*" /IM cmd.exe /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq ESP32 Sector*" /IM cmd.exe /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Dashboard*" /IM cmd.exe /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq MQTT Broker*" /IM cmd.exe /T >nul 2>&1
taskkill /F /IM mosquitto.exe >nul 2>&1

echo.
echo Simulation stopped.
echo ============================================================
timeout /t 3 /nobreak >nul