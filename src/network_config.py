"""Közös MQTT-végpont beállításai környezeti változókból."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class MqttConfig:
    """A publisher, a monitor és a dashboard által közösen használt végpont."""
    host: str
    port: int
    topic: str


def load_mqtt_config(environ: Mapping[str, str] | None = None) -> MqttConfig:
    """Betölti és ellenőrzi az MQTT-címet; alapból a helyi Mosquitto példányt használja."""
    source = os.environ if environ is None else environ
    host = str(source.get("BODYLINE_MQTT_HOST", "127.0.0.1")).strip()
    if not host:
        raise ValueError("A BODYLINE_MQTT_HOST nem lehet üres.")

    raw_port = str(source.get("BODYLINE_MQTT_PORT", "1883")).strip()
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("A BODYLINE_MQTT_PORT egész szám kell legyen.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("A BODYLINE_MQTT_PORT értéke 1 és 65535 közé essen.")

    topic = str(source.get("BODYLINE_MQTT_TOPIC", "welding/events")).strip()
    if not topic:
        raise ValueError("A BODYLINE_MQTT_TOPIC nem lehet üres.")
    return MqttConfig(host=host, port=port, topic=topic)


# A modul betöltésekor egyszer állítom elő a közös végpontot; minden komponens ezt importálja.
MQTT_CONFIG = load_mqtt_config()
BROKER_HOST = MQTT_CONFIG.host
BROKER_PORT = MQTT_CONFIG.port
MQTT_TOPIC = MQTT_CONFIG.topic
