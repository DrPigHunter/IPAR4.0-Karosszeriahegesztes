"""Generate simulated car-body spot-welding events and publish them over MQTT."""
from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
EVENT_TOPIC = "welding/events"
BODY_TYPES: dict[str, int] = {"Sedan": 80, "SUV": 120, "Compact": 60}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_body_events(body_type: str, fault_rate: float = 0.04, seed: int | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Create events. fault_rate is the chance of a missing point or abnormal parameters."""
    if body_type not in BODY_TYPES:
        raise ValueError(f"Ismeretlen karosszériatípus: {body_type}")
    if not 0 <= fault_rate <= 1:
        raise ValueError("A fault_rate értékének 0 és 1 között kell lennie.")
    rng = random.Random(seed)
    body_id = f"BODY-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    expected_count = BODY_TYPES[body_type]
    expected_ids = [f"W{i:03d}" for i in range(1, expected_count + 1)]
    events: list[dict[str, Any]] = []
    for point_id in expected_ids:
        if rng.random() < fault_rate * 0.35:
            continue  # simulate a missing message / weld record
        event: dict[str, Any] = {
            "event_type": "weld_result",
            "body_id": body_id,
            "body_type": body_type,
            "weld_id": point_id,
            "current_ka": round(rng.uniform(7.6, 10.4), 2),
            "weld_time_ms": round(rng.uniform(180, 320), 1),
            "electrode_force_kn": round(rng.uniform(2.8, 4.2), 2),
            "timestamp": utc_now(),
        }
        if rng.random() < fault_rate:
            parameter = rng.choice(["current_ka", "weld_time_ms", "electrode_force_kn"])
            event[parameter] = {"current_ka": 13.5, "weld_time_ms": 420.0, "electrode_force_kn": 5.8}[parameter]
        events.append(event)
        if rng.random() < fault_rate * 0.25:
            duplicate = dict(event)
            duplicate["timestamp"] = utc_now()
            duplicate["duplicate_simulated"] = True
            events.append(duplicate)
    events.append({
        "event_type": "body_complete",
        "body_id": body_id,
        "body_type": body_type,
        "expected_weld_ids": expected_ids,
        "expected_count": expected_count,
        "timestamp": utc_now(),
    })
    return body_id, events


def publish_events(events: list[dict[str, Any]], host: str = BROKER_HOST, port: int = BROKER_PORT, delay_ms: int = 8) -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"welding-publisher-{uuid.uuid4().hex[:8]}")
    client.connect(host, port, keepalive=30)
    client.loop_start()
    try:
        for event in events:
            info = client.publish(EVENT_TOPIC, json.dumps(event, ensure_ascii=False), qos=1)
            info.wait_for_publish(timeout=5)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publikálási hiba: {info.rc}")
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
    finally:
        client.loop_stop()
        client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Szimulált karosszéria-ponthegesztés MQTT-publisher")
    parser.add_argument("--body-type", choices=sorted(BODY_TYPES), default="Sedan")
    parser.add_argument("--fault-rate", type=float, default=0.04, help="Szimulált hibák valószínűsége (0..1)")
    parser.add_argument("--host", default=BROKER_HOST)
    parser.add_argument("--port", type=int, default=BROKER_PORT)
    parser.add_argument("--delay-ms", type=int, default=8)
    args = parser.parse_args()
    body_id, events = generate_body_events(args.body_type, args.fault_rate)
    publish_events(events, args.host, args.port, args.delay_ms)
    print(f"Elküldve: {body_id} | {args.body_type} | {len(events)-1} hegesztési esemény + lezáró üzenet")


if __name__ == "__main__":
    main()
