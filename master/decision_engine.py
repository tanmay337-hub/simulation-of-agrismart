"""
decision_engine.py — Rule-based irrigation decision engine.

This is a RULE-BASED engine. It is NOT a trained AI/ML model.
Designed with a clean interface so an ML model can be swapped in later
without changing the calling code.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SETTINGS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "settings.json"
)


class DecisionEngine:
    """
    Rule-based irrigation decision engine.

    Evaluates sensor readings against configurable thresholds and
    returns structured action decisions.  Can be replaced by an ML
    model by subclassing or duck-typing the same interface.
    """

    ENGINE_TYPE = "rule-based engine"  # Never claim to be an AI/ML model.

    def __init__(self, settings_path: str = SETTINGS_PATH) -> None:
        self._settings_path = settings_path
        self.thresholds: dict[str, float] = {}
        self._last_decisions: dict[str, dict[str, Any]] = {}
        self._load_thresholds()
        logger.info(
            "DecisionEngine initialised as %s with thresholds: %s",
            self.ENGINE_TYPE,
            self.thresholds,
        )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _load_thresholds(self) -> None:
        """Load threshold values from settings.json."""
        try:
            with open(self._settings_path, "r", encoding="utf-8") as fh:
                settings = json.load(fh)
            raw = settings.get("thresholds", {})
            self.thresholds = {
                "moisture_start": float(raw.get("moisture_start", 30)),
                "moisture_stop": float(raw.get("moisture_stop", 55)),
                "temp_alert": float(raw.get("temp_alert", 35)),
                "humidity_alert": float(raw.get("humidity_alert", 35)),
            }
            logger.debug("Thresholds loaded: %s", self.thresholds)
        except FileNotFoundError:
            logger.warning(
                "settings.json not found at %s — using built-in defaults.",
                self._settings_path,
            )
            self.thresholds = {
                "moisture_start": 30.0,
                "moisture_stop": 55.0,
                "temp_alert": 35.0,
                "humidity_alert": 35.0,
            }
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("Failed to parse thresholds: %s — using defaults.", exc)
            self.thresholds = {
                "moisture_start": 30.0,
                "moisture_stop": 55.0,
                "temp_alert": 35.0,
                "humidity_alert": 35.0,
            }

    def update_thresholds(self, new_thresholds: dict[str, float]) -> None:
        """
        Runtime threshold update (e.g. from dashboard).

        Only recognised keys are accepted; unknown keys are logged and ignored.
        """
        valid_keys = {"moisture_start", "moisture_stop", "temp_alert", "humidity_alert"}
        updated = {}
        for key, value in new_thresholds.items():
            if key in valid_keys:
                try:
                    self.thresholds[key] = float(value)
                    updated[key] = float(value)
                except (TypeError, ValueError) as exc:
                    logger.warning("Invalid value for threshold '%s': %s", key, exc)
            else:
                logger.warning("Unknown threshold key ignored: '%s'", key)
        logger.info("Thresholds updated at runtime: %s", updated)

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------

    def decide(
        self,
        sector_id: int | str,
        sensor_reading: dict[str, Any],
        current_valve_state: str,
        crisis: str = "normal",
    ) -> dict[str, Any]:
        """
        Evaluate one sensor reading and return an action decision.

        Parameters
        ----------
        sector_id:
            Sector identifier (int or str).
        sensor_reading:
            Dict with at minimum 'moisture' (%), and optionally
            'temperature' (°C) and 'humidity' (%).
        current_valve_state:
            Current valve state string: "OPEN" or "CLOSED".

        Returns
        -------
        dict with keys:
            action       — "OPEN" | "CLOSE" | "MAINTAIN"
            reason       — Human-readable explanation.
            sector_id    — Echoed back.
            timestamp    — ISO 8601 UTC string.
            engine_type  — Always "rule-based engine".
            alerts       — List of alert strings (may be empty).
        """
        sector_key = str(sector_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        moisture = float(sensor_reading.get("moisture", 0))
        temperature = sensor_reading.get("temperature")
        humidity = sensor_reading.get("humidity")

        moisture_start = self.thresholds["moisture_start"]
        moisture_stop = self.thresholds["moisture_stop"]

        # --- Environmental crisis overrides (safety & water conservation) ---
        if crisis == "rainstorm":
            action = "CLOSE" if current_valve_state == "OPEN" else "MAINTAIN"
            reason = (
                f"Rainstorm crisis active (moisture {moisture:.1f}%) — keeping valve CLOSED "
                "to prevent over-watering."
            )
        elif crisis == "frost" or (temperature is not None and float(temperature) <= 3.0):
            action = "CLOSE" if current_valve_state == "OPEN" else "MAINTAIN"
            reason = (
                f"Frost protection active (temp={temperature}°C) — locking valve CLOSED "
                "to protect lines and roots."
            )
        elif crisis == "water_supply_failure":
            action = "CLOSE" if current_valve_state == "OPEN" else "MAINTAIN"
            reason = (
                "Pump / water supply failure (0.0 L/m flow) — holding valve CLOSED "
                "to protect pump coil."
            )
        elif crisis == "heatwave":
            heat_start = min(moisture_stop - 2.0, moisture_start + 5.0)
            if moisture < heat_start:
                action = "OPEN"
                reason = (
                    f"Heatwave crisis active: moisture {moisture:.1f}% < accelerated heat "
                    f"threshold ({heat_start:.0f}%). Emergency irrigation OPEN."
                )
            elif moisture > moisture_stop:
                action = "CLOSE"
                reason = (
                    f"Soil moisture {moisture:.1f}% exceeds stop threshold ({moisture_stop}%). "
                    "Valve closed."
                )
            else:
                action = "MAINTAIN"
                reason = (
                    f"Heatwave active: moisture {moisture:.1f}% in buffer band. Holding "
                    f"valve ({current_valve_state})."
                )
        # --- Core irrigation rule (hysteresis band) ---
        elif moisture < moisture_start:
            action = "OPEN"
            reason = (
                f"Soil moisture {moisture:.1f}% is below the irrigation start "
                f"threshold ({moisture_start}%). Valve opened to irrigate."
            )
        elif moisture > moisture_stop:
            action = "CLOSE"
            reason = (
                f"Soil moisture {moisture:.1f}% exceeds the irrigation stop "
                f"threshold ({moisture_stop}%). Valve closed to prevent over-watering."
            )
        else:
            # Hysteresis zone — maintain current state to avoid rapid switching.
            action = "MAINTAIN"
            reason = (
                f"Soil moisture {moisture:.1f}% is within the hysteresis band "
                f"({moisture_start}%–{moisture_stop}%). Current valve state "
                f"({current_valve_state}) maintained."
            )

        # --- Conditional alerts ---
        alerts: list[str] = []

        if temperature is not None:
            try:
                temp_f = float(temperature)
                if temp_f > self.thresholds["temp_alert"]:
                    alerts.append("high_temperature")
                    logger.warning(
                        "Sector %s: high temperature alert (%.1f°C > %.1f°C threshold).",
                        sector_key,
                        temp_f,
                        self.thresholds["temp_alert"],
                    )
            except (TypeError, ValueError):
                logger.debug("Could not parse temperature value: %s", temperature)

        if humidity is not None:
            try:
                hum_f = float(humidity)
                if hum_f < self.thresholds["humidity_alert"]:
                    alerts.append("low_humidity")
                    logger.warning(
                        "Sector %s: low humidity alert (%.1f%% < %.1f%% threshold).",
                        sector_key,
                        hum_f,
                        self.thresholds["humidity_alert"],
                    )
            except (TypeError, ValueError):
                logger.debug("Could not parse humidity value: %s", humidity)

        decision: dict[str, Any] = {
            "action": action,
            "reason": reason,
            "sector_id": sector_id,
            "timestamp": now_iso,
            "engine_type": self.ENGINE_TYPE,
            "alerts": alerts,
            "moisture_observed": moisture,
        }

        self._last_decisions[sector_key] = decision
        logger.info(
            "Sector %s decision: action=%s alerts=%s moisture=%.1f%%",
            sector_key,
            action,
            alerts,
            moisture,
        )
        return decision

    # ------------------------------------------------------------------
    # Inspection / explainability
    # ------------------------------------------------------------------

    def explain_last_decision(self, sector_id: int | str) -> dict[str, Any] | None:
        """
        Return the last decision dict for a sector, for display/logging.

        Returns None if no decision has been made for that sector yet.
        """
        return self._last_decisions.get(str(sector_id))

    def get_all_last_decisions(self) -> dict[str, dict[str, Any]]:
        """Return last decisions for every sector that has been evaluated."""
        return dict(self._last_decisions)

    def describe(self) -> str:
        """Return a human-readable description of this engine."""
        return (
            f"Engine type : {self.ENGINE_TYPE}\n"
            f"Thresholds  : moisture_start={self.thresholds['moisture_start']}%, "
            f"moisture_stop={self.thresholds['moisture_stop']}%, "
            f"temp_alert={self.thresholds['temp_alert']}°C, "
            f"humidity_alert={self.thresholds['humidity_alert']}%\n"
            f"Note        : This system uses deterministic threshold rules, "
            f"not a trained ML model."
        )
