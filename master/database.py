"""
database.py — SQLite persistence layer for the Smart Agriculture System.

Database file: data/farm_history.db (relative to the project root).

Tables
------
sensor_readings  — time-series sensor data per sector
commands         — irrigation commands issued
acknowledgments  — command acknowledgements from field nodes
alerts           — system/environment alerts
events           — general system events (start-up, faults, etc.)
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

logger = logging.getLogger(__name__)

# Resolve the data directory relative to this file's location (project root).
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "farm_history.db")


class Database:
    """
    SQLite-backed persistence layer for sensor readings, commands,
    acknowledgements, alerts, and system events.

    Parameters
    ----------
    db_path : str
        Absolute or relative path to the SQLite database file.
        Parent directories are created automatically.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self.init_db()
        logger.info("Database initialised at '%s'.", self._db_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that yields a configured connection and commits/rolls back."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create all tables if they do not already exist."""
        ddl_statements = [
            # ---- sensor_readings ----
            """
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_id             TEXT    NOT NULL,
                node_id               TEXT,
                moisture              REAL,
                temperature           REAL,
                humidity              REAL,
                light_lux             REAL,
                valve_state           TEXT,
                flow_rate_lpm         REAL,
                water_consumed_litres REAL,
                sequence_number       INTEGER,
                raw_payload           TEXT,
                recorded_at           TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_sr_sector ON sensor_readings(sector_id)",
            "CREATE INDEX IF NOT EXISTS idx_sr_time   ON sensor_readings(recorded_at)",

            # ---- commands ----
            """
            CREATE TABLE IF NOT EXISTS commands (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                cmd_id          TEXT    NOT NULL UNIQUE,
                sector_id       TEXT    NOT NULL,
                action          TEXT    NOT NULL,
                source          TEXT    DEFAULT 'master',
                issued_at       TEXT    NOT NULL,
                acked           INTEGER NOT NULL DEFAULT 0
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_cmd_sector ON commands(sector_id)",
            "CREATE INDEX IF NOT EXISTS idx_cmd_acked  ON commands(acked)",

            # ---- acknowledgments ----
            """
            CREATE TABLE IF NOT EXISTS acknowledgments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                cmd_id      TEXT    NOT NULL,
                sector_id   TEXT    NOT NULL,
                status      TEXT    NOT NULL,
                valve_state TEXT,
                reason      TEXT,
                acked_at    TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ack_cmd ON acknowledgments(cmd_id)",

            # ---- alerts ----
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_id   TEXT,
                alert_type  TEXT    NOT NULL,
                message     TEXT,
                severity    TEXT    NOT NULL DEFAULT 'WARNING',
                resolved    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_alert_sector ON alerts(sector_id)",
            "CREATE INDEX IF NOT EXISTS idx_alert_time   ON alerts(created_at)",

            # ---- events ----
            """
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_id   TEXT,
                event_type  TEXT    NOT NULL,
                description TEXT,
                payload     TEXT,
                created_at  TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_event_time ON events(created_at)",
        ]

        with self._get_conn() as conn:
            for stmt in ddl_statements:
                conn.execute(stmt)
        logger.debug("Database schema verified/created.")

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def insert_sensor_reading(
        self,
        sector_id: int | str,
        reading_dict: dict[str, Any],
        timestamp: str | None = None,
    ) -> None:
        """
        Persist a sensor reading snapshot.

        Known fields are stored in named columns; the full dict is also
        stored as raw JSON for future-proofing.
        """
        now = timestamp or datetime.now(timezone.utc).isoformat()
        sql = """
            INSERT INTO sensor_readings
                (sector_id, node_id, moisture, temperature, humidity,
                 light_lux, valve_state, flow_rate_lpm, water_consumed_litres,
                 sequence_number, raw_payload, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with self._get_conn() as conn:
                conn.execute(
                    sql,
                    (
                        str(sector_id),
                        reading_dict.get("node_id"),
                        reading_dict.get("moisture"),
                        reading_dict.get("temperature"),
                        reading_dict.get("humidity"),
                        reading_dict.get("light_lux"),
                        reading_dict.get("valve_state"),
                        reading_dict.get("flow_rate_lpm"),
                        reading_dict.get("water_consumed_litres"),
                        reading_dict.get("sequence_number"),
                        json.dumps(reading_dict, default=str),
                        reading_dict.get("timestamp", now),
                    ),
                )
            logger.debug("Sensor reading inserted for sector %s.", sector_id)
        except sqlite3.Error as exc:
            logger.error("insert_sensor_reading failed: %s", exc)

    def insert_command(
        self,
        cmd_id: str,
        sector_id: int | str,
        action: str,
        timestamp: str | None = None,
        source: str = "master",
    ) -> None:
        """Record an irrigation command that has been published."""
        issued_at = timestamp or datetime.now(timezone.utc).isoformat()
        sql = """
            INSERT OR IGNORE INTO commands (cmd_id, sector_id, action, source, issued_at, acked)
            VALUES (?, ?, ?, ?, ?, 0)
        """
        try:
            with self._get_conn() as conn:
                conn.execute(sql, (cmd_id, str(sector_id), action, source, issued_at))
            logger.debug("Command %s inserted (sector=%s action=%s).", cmd_id, sector_id, action)
        except sqlite3.Error as exc:
            logger.error("insert_command failed: %s", exc)

    def insert_ack(
        self,
        cmd_id: str,
        sector_id: int | str,
        status: str,
        timestamp: str | None = None,
        valve_state: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Record an acknowledgement received from a field node."""
        acked_at = timestamp or datetime.now(timezone.utc).isoformat()
        sql_ack = """
            INSERT INTO acknowledgments (cmd_id, sector_id, status, valve_state, reason, acked_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        sql_mark = "UPDATE commands SET acked = 1 WHERE cmd_id = ?"
        try:
            with self._get_conn() as conn:
                conn.execute(sql_ack, (cmd_id, str(sector_id), status, valve_state, reason, acked_at))
                conn.execute(sql_mark, (cmd_id,))
            logger.debug("Ack for command %s recorded (status=%s).", cmd_id, status)
        except sqlite3.Error as exc:
            logger.error("insert_ack failed: %s", exc)

    def insert_alert(
        self,
        sector_id: int | str | None,
        alert_type: str,
        message: str,
        timestamp: str | None = None,
        severity: str = "WARNING",
    ) -> None:
        """Record a sensor or system alert."""
        created_at = timestamp or datetime.now(timezone.utc).isoformat()
        sql = """
            INSERT INTO alerts (sector_id, alert_type, message, severity, resolved, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
        """
        try:
            with self._get_conn() as conn:
                conn.execute(
                    sql,
                    (
                        str(sector_id) if sector_id is not None else None,
                        alert_type,
                        message,
                        severity,
                        created_at,
                    ),
                )
            logger.debug("Alert '%s' inserted for sector %s.", alert_type, sector_id)
        except sqlite3.Error as exc:
            logger.error("insert_alert failed: %s", exc)

    def resolve_alerts(self, sector_id: int | str | None = None, alert_type: str | None = None) -> None:
        """Mark matching alerts as resolved."""
        clauses = ["resolved = 0"]
        params: list[Any] = []
        if sector_id is not None:
            clauses.append("sector_id = ?")
            params.append(str(sector_id))
        if alert_type is not None:
            clauses.append("alert_type = ?")
            params.append(alert_type)
        sql = f"UPDATE alerts SET resolved = 1 WHERE {' AND '.join(clauses)}"
        try:
            with self._get_conn() as conn:
                conn.execute(sql, tuple(params))
        except sqlite3.Error as exc:
            logger.error("resolve_alerts failed: %s", exc)

    def insert_event(
        self,
        event_type: str,
        description: str = "",
        timestamp: str | None = None,
        sector_id: int | str | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> None:
        """Record a system lifecycle, command, ack, or fault event."""
        created_at = timestamp or datetime.now(timezone.utc).isoformat()
        payload_str = (
            json.dumps(payload, default=str)
            if isinstance(payload, dict)
            else (str(payload) if payload is not None else None)
        )
        sql = """
            INSERT INTO events (sector_id, event_type, description, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
        """
        try:
            with self._get_conn() as conn:
                conn.execute(
                    sql,
                    (
                        str(sector_id) if sector_id is not None else None,
                        event_type,
                        description,
                        payload_str,
                        created_at,
                    ),
                )
            logger.debug("Event '%s' inserted.", event_type)
        except sqlite3.Error as exc:
            logger.error("insert_event failed: %s", exc)

    def get_total_water_consumed(self) -> float:
        """Sum the latest reported water_consumed_litres across all sectors."""
        sql = """
            SELECT COALESCE(SUM(water_consumed_litres), 0.0) AS total
            FROM sensor_readings s1
            WHERE id = (
                SELECT MAX(s2.id)
                FROM sensor_readings s2
                WHERE s2.sector_id = s1.sector_id
                  AND s2.water_consumed_litres IS NOT NULL
            )
        """
        try:
            with self._get_conn() as conn:
                row = conn.execute(sql).fetchone()
            return float(row["total"]) if row and row["total"] is not None else 0.0
        except sqlite3.Error as exc:
            logger.error("get_total_water_consumed failed: %s", exc)
            return 0.0

    def close(self) -> None:
        """No persistent single connection is held; provided for lifecycle symmetry."""
        logger.info("Database closed.")

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_latest_readings(
        self, sector_id: int | str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Return the most recent *limit* sensor readings for *sector_id*,
        newest first.
        """
        sql = """
            SELECT *
            FROM   sensor_readings
            WHERE  sector_id = ?
            ORDER  BY recorded_at DESC
            LIMIT  ?
        """
        try:
            with self._get_conn() as conn:
                rows = conn.execute(sql, (str(sector_id), limit)).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("get_latest_readings failed: %s", exc)
            return []

    def get_command_history(
        self, sector_id: int | str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Return the most recent *limit* commands for *sector_id*,
        joined with their acknowledgement status.
        """
        sql = """
            SELECT
                c.cmd_id,
                c.sector_id,
                c.action,
                c.issued_at,
                c.acked,
                a.status    AS ack_status,
                a.acked_at
            FROM       commands c
            LEFT JOIN  acknowledgments a ON a.cmd_id = c.cmd_id
            WHERE      c.sector_id = ?
            ORDER      BY c.issued_at DESC
            LIMIT      ?
        """
        try:
            with self._get_conn() as conn:
                rows = conn.execute(sql, (str(sector_id), limit)).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("get_command_history failed: %s", exc)
            return []

    def get_unacknowledged_commands(
        self, timeout_seconds: int = 30
    ) -> list[dict[str, Any]]:
        """
        Return commands that have not been acknowledged and whose
        *issued_at* is older than *timeout_seconds* ago.

        These are candidates for retry or alerting.
        """
        sql = """
            SELECT *
            FROM   commands
            WHERE  acked = 0
              AND  datetime(issued_at) <= datetime('now', ? || ' seconds')
            ORDER  BY issued_at ASC
        """
        param = f"-{int(timeout_seconds)}"
        try:
            with self._get_conn() as conn:
                rows = conn.execute(sql, (param,)).fetchall()
            if rows:
                logger.warning(
                    "%d unacknowledged command(s) older than %ds.",
                    len(rows),
                    timeout_seconds,
                )
            return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("get_unacknowledged_commands failed: %s", exc)
            return []

    def get_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent *limit* alerts, newest first."""
        sql = "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?"
        try:
            with self._get_conn() as conn:
                rows = conn.execute(sql, (limit,)).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("get_alerts failed: %s", exc)
            return []

    def get_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent *limit* system events, newest first."""
        sql = "SELECT * FROM events ORDER BY created_at DESC LIMIT ?"
        try:
            with self._get_conn() as conn:
                rows = conn.execute(sql, (limit,)).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.error("get_events failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def purge_old_readings(self, older_than_days: int = 30) -> int:
        """
        Delete sensor readings older than *older_than_days* days.

        Returns the number of rows deleted.
        """
        sql = """
            DELETE FROM sensor_readings
            WHERE datetime(recorded_at) < datetime('now', ? || ' days')
        """
        param = f"-{int(older_than_days)}"
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(sql, (param,))
                deleted = cursor.rowcount
            logger.info("Purged %d sensor_readings rows older than %d days.", deleted, older_than_days)
            return deleted
        except sqlite3.Error as exc:
            logger.error("purge_old_readings failed: %s", exc)
            return 0
