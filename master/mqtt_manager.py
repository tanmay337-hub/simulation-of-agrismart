"""
mqtt_manager.py — Resilient MQTT client wrapper.

Wraps paho-mqtt with:
- Automatic exponential-backoff reconnection (max 60 s).
- JSON payload serialisation on publish.
- Per-instance counters for messages sent/received.
- Thread-safe reconnection guard.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# Reconnection backoff parameters
_BACKOFF_BASE = 2.0       # seconds
_BACKOFF_MAX = 60.0       # seconds
_BACKOFF_MULTIPLIER = 2.0


class MQTTManager:
    """
    Resilient MQTT client with automatic exponential-backoff reconnection.

    Parameters
    ----------
    broker : str
        Hostname or IP of the MQTT broker.
    port : int
        Broker port (typically 1883).
    client_id : str
        Unique MQTT client identifier.
    on_message_callback : callable, optional
        Called with (topic: str, payload: dict) for every inbound message.
        If the payload cannot be decoded as JSON, the raw string is passed.
    keepalive : int
        MQTT keepalive interval in seconds (default 60).
    """

    def __init__(
        self,
        broker: str,
        port: int,
        client_id: str = "smart_agri_client",
        on_message_callback: Callable[[str, Any], None] | None = None,
        on_connect_callback: Callable[[], None] | None = None,
        on_disconnect_callback: Callable[[], None] | None = None,
        keepalive: int = 60,
    ) -> None:
        self._broker = broker
        self._port = port
        self._client_id = client_id
        self._on_message_callback = on_message_callback
        self._on_connect_callback = on_connect_callback
        self._on_disconnect_callback = on_disconnect_callback
        self._keepalive = keepalive

        if hasattr(mqtt, "CallbackAPIVersion"):
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id=client_id,
                protocol=mqtt.MQTTv311,
            )
        else:
            self._client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._connected = False
        self._reconnect_flag = False
        self._reconnect_lock = threading.Lock()
        self._reconnect_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Metrics
        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.last_connected_at: datetime | None = None

        # Subscriptions to restore after reconnect
        self._subscriptions: set[str] = set()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True if the MQTT client is currently connected."""
        return self._connected

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Connect to the broker synchronously.

        Returns True on success, False on failure.
        """
        try:
            logger.info(
                "Connecting to MQTT broker %s:%s as '%s' …",
                self._broker,
                self._port,
                self._client_id,
            )
            self._client.connect(self._broker, self._port, keepalive=self._keepalive)
            self._client.loop_start()
            # Give the broker a moment to acknowledge the CONNACK.
            deadline = time.monotonic() + 5.0
            while not self._connected and time.monotonic() < deadline:
                time.sleep(0.1)
            if self._connected:
                logger.info("Connected to MQTT broker %s:%s.", self._broker, self._port)
            else:
                logger.warning("connect() timed out waiting for CONNACK.")
            return self._connected
        except Exception as exc:
            logger.error("MQTT connect failed: %s", exc)
            return False

    def disconnect(self) -> None:
        """Cleanly disconnect from the broker and stop the network loop."""
        self._stop_event.set()
        self._reconnect_flag = False
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception as exc:
            logger.debug("Exception during disconnect (safe to ignore): %s", exc)
        self._connected = False
        logger.info("Disconnected from MQTT broker.")

    def reconnect(self) -> None:
        """
        Attempt to reconnect with exponential backoff.

        Called automatically on disconnect; may also be called manually.
        """
        with self._reconnect_lock:
            if self._reconnect_thread and self._reconnect_thread.is_alive():
                logger.debug("Reconnect already in progress — skipping duplicate call.")
                return
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop, daemon=True, name="mqtt-reconnect"
            )
            self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """Background thread: retry connection with exponential backoff."""
        backoff = _BACKOFF_BASE
        attempt = 0
        while not self._stop_event.is_set() and not self._connected:
            attempt += 1
            logger.info(
                "Reconnect attempt #%d in %.1f s …", attempt, backoff
            )
            self._stop_event.wait(timeout=backoff)
            if self._stop_event.is_set():
                break
            try:
                self._client.reconnect()
                # Wait briefly for CONNACK
                deadline = time.monotonic() + 5.0
                while not self._connected and time.monotonic() < deadline:
                    time.sleep(0.1)
                if self._connected:
                    logger.info("Reconnected on attempt #%d.", attempt)
                    self._resubscribe()
                    return
            except Exception as exc:
                logger.warning("Reconnect attempt #%d failed: %s", attempt, exc)
            backoff = min(backoff * _BACKOFF_MULTIPLIER, _BACKOFF_MAX)
        logger.info("Reconnect loop exiting (stop_event=%s).", self._stop_event.is_set())

    # ------------------------------------------------------------------
    # Subscribe / Unsubscribe
    # ------------------------------------------------------------------

    def subscribe(self, topic: str, qos: int = 1) -> None:
        """Subscribe to *topic* (and remember it for reconnects)."""
        self._subscriptions.add(topic)
        if self._connected:
            self._client.subscribe(topic, qos=qos)
            logger.info("Subscribed to topic '%s' (qos=%d).", topic, qos)
        else:
            logger.warning(
                "Not connected — topic '%s' queued for subscription after reconnect.",
                topic,
            )

    def unsubscribe(self, topic: str) -> None:
        """Unsubscribe from *topic* and stop tracking it."""
        self._subscriptions.discard(topic)
        if self._connected:
            self._client.unsubscribe(topic)
            logger.info("Unsubscribed from topic '%s'.", topic)

    def _resubscribe(self) -> None:
        """Re-apply all tracked subscriptions after a reconnect."""
        for topic in self._subscriptions:
            try:
                self._client.subscribe(topic, qos=1)
                logger.debug("Re-subscribed to '%s' after reconnect.", topic)
            except Exception as exc:
                logger.error("Failed to re-subscribe to '%s': %s", topic, exc)

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    def publish(
        self,
        topic: str,
        payload_dict: dict[str, Any] | str,
        qos: int = 1,
        retain: bool = False,
    ) -> bool:
        """
        Serialise *payload_dict* to JSON and publish to *topic*.

        Returns True if the message was handed to paho successfully,
        False otherwise (not connected, serialisation error, etc.).
        """
        if not self._connected:
            logger.warning("Cannot publish to '%s': not connected.", topic)
            return False
        try:
            payload_str = (
                payload_dict
                if isinstance(payload_dict, str)
                else json.dumps(payload_dict, default=str)
            )
        except (TypeError, ValueError) as exc:
            logger.error("Failed to serialise payload for '%s': %s", topic, exc)
            return False
        result = self._client.publish(topic, payload=payload_str, qos=qos, retain=retain)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            self.messages_sent += 1
            logger.debug("Published to '%s' (qos=%d, retain=%s).", topic, qos, retain)
            return True
        else:
            logger.error(
                "Publish to '%s' failed with rc=%d.", topic, result.rc
            )
            return False

    # ------------------------------------------------------------------
    # Paho callbacks
    # ------------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict,
        rc: int,
    ) -> None:
        if rc == 0:
            self._connected = True
            self._reconnect_flag = False
            self.last_connected_at = datetime.now(timezone.utc)
            logger.info(
                "MQTT on_connect OK — broker=%s:%s client_id=%s",
                self._broker,
                self._port,
                self._client_id,
            )
            self._resubscribe()
            if self._on_connect_callback is not None:
                try:
                    self._on_connect_callback()
                except Exception as exc:
                    logger.error("on_connect_callback raised exception: %s", exc)
        else:
            self._connected = False
            logger.error(
                "MQTT on_connect refused — rc=%d (check broker credentials/ACLs).", rc
            )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        rc: int,
    ) -> None:
        self._connected = False
        if self._on_disconnect_callback is not None:
            try:
                self._on_disconnect_callback()
            except Exception as exc:
                logger.error("on_disconnect_callback raised exception: %s", exc)
        if rc == 0:
            logger.info("MQTT cleanly disconnected.")
        else:
            logger.warning(
                "MQTT unexpected disconnect (rc=%d) — scheduling reconnect.", rc
            )
            self._reconnect_flag = True
            if not self._stop_event.is_set():
                self.reconnect()

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        self.messages_received += 1
        topic = message.topic
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = message.payload.decode("utf-8", errors="replace")
            logger.debug("Non-JSON payload on topic '%s'.", topic)

        logger.debug("Message received on '%s'.", topic)

        if self._on_message_callback is not None:
            try:
                self._on_message_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "on_message_callback raised an exception for topic '%s': %s",
                    topic,
                    exc,
                )

    # ------------------------------------------------------------------
    # Stats / diagnostics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return current connection statistics."""
        return {
            "broker": f"{self._broker}:{self._port}",
            "client_id": self._client_id,
            "is_connected": self._connected,
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "last_connected_at": (
                self.last_connected_at.isoformat() if self.last_connected_at else None
            ),
            "active_subscriptions": list(self._subscriptions),
        }
