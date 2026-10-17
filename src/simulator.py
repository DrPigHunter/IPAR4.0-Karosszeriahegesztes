"""Simulate a welding cycle from the GitHub-versioned XLSX catalogue and publish via MQTT."""
from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

from src.catalog import get_configuration, list_configurations

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
EVENT_TOPIC = "welding/events"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_body_events(
    config_id: str, fault_rate: float = 0.0001, seed: int | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """Generate a cycle using expected IDs, per-point nominal values, and limits from XLSX."""
    if not 0 <= fault_rate <= 1:
        raise ValueError("A fault_rate értékének 0 és 1 között kell lennie.")
    config = get_configuration(config_id)
    rng = random.Random(seed)
    body_id = f"BODY-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    common = {
        "body_id": body_id, "config_id": config_id, "body_type": config["label"],
        "brand": config["brand"], "model": config["model"], "part": config["part"],
    }
    expected_ids = list(config["expected_weld_ids"])
    limits = config["limits"]
    events: list[dict[str, Any]] = [{
        **common, "event_type": "body_start", "expected_weld_ids": expected_ids,
        "expected_count": len(expected_ids), "timestamp": utc_now(),
    }]

    for point in config["points"]:
        if rng.random() < fault_rate * 0.35:
            continue  # Simulated lost weld-result event.
        # Normal values are derived from the point's Excel nominal recipe with modest noise.
        event: dict[str, Any] = {
            **common, "event_type": "weld_result", "weld_id": point["weld_id"],
            "current_ka": round(max(limits.current_min, min(limits.current_max,
                point["nominal_current_ka"] + rng.uniform(-0.12, 0.12))), 2),
            "weld_time_ms": round(max(limits.weld_time_min, min(limits.weld_time_max,
                point["nominal_weld_time_ms"] + rng.uniform(-4.0, 4.0))), 1),
            "electrode_force_kn": round(max(limits.force_min, min(limits.force_max,
                point["nominal_electrode_force_kn"] + rng.uniform(-0.04, 0.04))), 2),
            "timestamp": utc_now(),
        }
        if rng.random() < fault_rate:
            key = rng.choice(["current_ka", "weld_time_ms", "electrode_force_kn"])
            event[key] = {
                "current_ka": limits.current_max + 2.0,
                "weld_time_ms": limits.weld_time_max + 60.0,
                "electrode_force_kn": limits.force_max + 1.0,
            }[key]
        events.append(event)

        if rng.random() < fault_rate * 0.25:
            duplicate = dict(event)
            duplicate["timestamp"] = utc_now()
            duplicate["duplicate_simulated"] = True
            events.append(duplicate)

        if rng.random() < fault_rate * 0.08:
            events.append({
                **event, "weld_id": f"X{rng.randint(1, 999):03d}",
                "timestamp": utc_now(), "unexpected_simulated": True,
            })

    events.append({
        **common, "event_type": "body_complete", "expected_weld_ids": expected_ids,
        "expected_count": len(expected_ids), "timestamp": utc_now(),
    })
    return body_id, events


def publish_events(
    events: list[dict[str, Any]], host: str = BROKER_HOST, port: int = BROKER_PORT, delay_ms: int = 8
) -> None:
    """Publish events in order using MQTT QoS 1."""
    if delay_ms < 0:
        raise ValueError("A delay_ms nem lehet negatív.")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"welding-publisher-{uuid.uuid4().hex[:8]}")
    client.connect(host, port, keepalive=30)
    client.loop_start()
    try:
        for event in events:
            info = client.publish(EVENT_TOPIC, json.dumps(event, ensure_ascii=False), qos=1)
            info.wait_for_publish(timeout=5)
            if info.rc != mqtt.MQTT_ERR_SUCCESS or not info.is_published():
                raise RuntimeError(f"MQTT publikálási hiba: {info.rc}")
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
    finally:
        client.loop_stop()
        client.disconnect()


def main() -> None:
    configs = list_configurations()
    labels = {cfg["config_id"]: cfg["label"] for cfg in configs}
    parser = argparse.ArgumentParser(description="Excel katalógus alapú karosszéria-/alkatrész-hegesztés szimulátor")
    parser.add_argument("--config-id", choices=sorted(labels), default=configs[0]["config_id"])
    parser.add_argument("--fault-rate", type=float, default=0.0001, help="Szimulált hibák valószínűsége (0..1; alapérték: 0.0001)")
    parser.add_argument("--host", default=BROKER_HOST)
    parser.add_argument("--port", type=int, default=BROKER_PORT)
    parser.add_argument("--delay-ms", type=int, default=8)
    args = parser.parse_args()
    body_id, events = generate_body_events(args.config_id, args.fault_rate)
    publish_events(events, args.host, args.port, args.delay_ms)
    weld_events = sum(event.get("event_type") == "weld_result" for event in events)
    print(f"Elküldve: {body_id} | {labels[args.config_id]} | {weld_events} hegesztési üzenet + indító és lezáró esemény")


if __name__ == "__main__":
    main()
