"""Generate XLSX-based welding measurements with controllable per-point variations."""
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
from src.factory_settings import DEFAULT_NON_WEAR_DEFECT_PROBABILITY
from src.wear_control import (
    COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN,
    COOLANT_INLET_TARGET_MAX_C,
    COOLANT_OUTLET_TARGET_MAX_C,
    DEFAULT_WEAR_PER_POINT_PERCENT,
    apply_electrode_wear,
)

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
EVENT_TOPIC = "welding/events"

FAULT_MODES = ("within_limits", "outside_limits")
MAX_FAULT_PROBABILITY = 0.001  # 0.1% per welding point
MAX_NON_WEAR_DEFECT_PROBABILITY = 0.001  # 0.1% per welding point
NON_WEAR_FAULT_CAUSE_HYPOTHESES = (
    "SURFACE_CONTAMINATION_OR_COATING_VARIATION",
    "PART_FIT_UP_OR_ELECTRODE_ALIGNMENT",
    "PROCESS_PARAMETER_VARIATION",
)


# UTC időbélyeget adok az eseményekhez, hogy a generálási és fogadási idő később összehasonlítható legyen.
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# A szándékos teszthibát a kiválasztott paraméter határán belülre vagy egy felbontási lépéssel kívülre állítom.
def _apply_point_variation(
    event: dict[str, Any],
    limits: Any,
    rng: random.Random,
    mode: str,
) -> None:
    """Vary one measurement either just inside limits or just outside by one resolution step."""
    choices = {
        "current_ka": (limits.current_min, limits.current_max, 0.01, 2),
        "weld_time_ms": (limits.weld_time_min, limits.weld_time_max, 0.1, 1),
        "electrode_force_kn": (limits.force_min, limits.force_max, 0.01, 2),
    }
    key = rng.choice(list(choices))
    lower, upper, resolution, digits = choices[key]
    go_high = rng.choice([True, False])

    if mode == "within_limits":
        # Move near the chosen edge, but never across it. That result must pass validation.
        value = upper - resolution if go_high else lower + resolution
        value = round(value, digits)
        value = min(upper, max(lower, value))
        event[key] = value
        event["simulated_variation"] = "WITHIN_ACCEPTED_LIMITS"
    elif mode == "outside_limits":
        # A deliberately small one-step violation, so the monitor catches a real boundary breach.
        value = upper + resolution if go_high else lower - resolution
        event[key] = round(value, digits)
        event["simulated_variation"] = "OUTSIDE_ACCEPTED_LIMITS"
    else:
        raise ValueError(
            f"Ismeretlen hibamód: {mode!r}. Választható: {', '.join(FAULT_MODES)}"
        )


# A kopástól független, ritka háttérhibát külön jelöléssel injektálom; az okcímke szimulált hipotézis, nem valós gyökérok-diagnózis.
def _apply_non_wear_process_defect(
    event: dict[str, Any], limits: Any, rng: random.Random
) -> None:
    """Inject a rare, wear-independent process defect for simulation/testing.

    A single process measurement is moved just outside the catalog limit so the
    existing monitor can detect it. The cause is only a synthetic hypothesis label;
    the simulator does not physically model contamination or part fit-up.
    """
    _apply_point_variation(event, limits, rng, "outside_limits")
    event["simulated_variation"] = "BACKGROUND_PROCESS_DEFECT"
    event["non_wear_process_defect"] = True
    event["simulated_failure_source"] = "NON_WEAR_PROCESS_VARIATION"
    event["simulated_failure_cause_hypothesis"] = rng.choice(NON_WEAR_FAULT_CAUSE_HYPOTHESES)


# Egy kiválasztott modell teljes oldalfal-eseménysorát állítom elő a katalógus pontlistája, paraméterei és a kopásmodell alapján.
def generate_body_events(
    config_id: str,
    fault_rate: float = 0.0,
    seed: int | None = None,
    fault_mode: str = "within_limits",
    wear_state: dict[str, Any] | None = None,
    wear_per_point_percent: float = DEFAULT_WEAR_PER_POINT_PERCENT,
    wear_enabled: bool = False,
    auto_correct_wear: bool = True,
    coolant_flow_l_min: float = COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN,
    coolant_inlet_temp_c: float = COOLANT_INLET_TARGET_MAX_C,
    coolant_outlet_temp_c: float = COOLANT_OUTLET_TARGET_MAX_C,
    non_wear_defect_probability: float = DEFAULT_NON_WEAR_DEFECT_PROBABILITY,
) -> tuple[str, list[dict[str, Any]]]:
    """Generate a simulated sidewall.

    ``fault_rate`` is deliberate test injection (0.001 = 0.1% per point).
    ``non_wear_defect_probability`` is a separate, rare background process-defect
    probability independent of the electrode-wear state. The default 0.01% per
    point is a documented demo assumption, not an industry-wide measured rate.
    Background defects are represented by one monitored parameter-limit breach so
    the existing quality monitor can send the sidewall to rework.
    """
    if not 0 <= fault_rate <= MAX_FAULT_PROBABILITY:
        raise ValueError("A pontonkénti hibavalószínűség 0 és 0.001 között lehet (0–0,1%).")
    if not 0.0 <= non_wear_defect_probability <= MAX_NON_WEAR_DEFECT_PROBABILITY:
        raise ValueError("A kopástól független hibavalószínűség 0 és 0.001 közé essen (0–0,1%).")
    if fault_mode not in FAULT_MODES:
        raise ValueError(f"Ismeretlen hibamód: {fault_mode!r}")

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

    # Minden katalógus szerinti ponthoz külön, azonosítható eseményt készítek.
    for point in config["points"]:
        # Regular measurements have small natural-looking noise and are clamped inside
        # the model-specific acceptable range. No drop/duplicate/unexpected events are
        # injected by the per-point probability control.
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
        if fault_rate > 0 and rng.random() < fault_rate:
            _apply_point_variation(event, limits, rng, fault_mode)
        # A second probability is separate from the wear model: even a fresh
        # electrode can occasionally produce an unacceptable simulated weld.
        if non_wear_defect_probability > 0 and rng.random() < non_wear_defect_probability:
            _apply_non_wear_process_defect(event, limits, rng)
        events.append(event)

    events.append({
        **common, "event_type": "body_complete", "expected_weld_ids": expected_ids,
        "expected_count": len(expected_ids), "timestamp": utc_now(),
    })
    # Keep the wear subsystem optional for callers that use the original simulator
    # API. The dashboard passes a shared state dictionary to accumulate wear per run.
    if wear_enabled or wear_state is not None:
        events[-1]["electrode_wear_summary"] = apply_electrode_wear(
            events,
            config,
            wear_state,
            wear_per_point_percent=wear_per_point_percent,
            wear_enabled=wear_enabled,
            auto_correct=auto_correct_wear,
            coolant_flow_l_min=coolant_flow_l_min,
            coolant_inlet_temp_c=coolant_inlet_temp_c,
            coolant_outlet_temp_c=coolant_outlet_temp_c,
        )
    return body_id, events


# Az eseményeket sorrendben publikálom MQTT-n, és megvárom a QoS 1 üzenetküldés lezárását.
def publish_events(
    events: list[dict[str, Any]], host: str = BROKER_HOST, port: int = BROKER_PORT, delay_ms: float = 90.0
) -> None:
    """Publish ordered events with QoS 1 acknowledgements checked after enqueueing.

    The caller controls the inter-message pause. The dashboard computes this
    from the selected model's event count to target a nominal 95-second cycle;
    direct calls that omit delay_ms retain the 90 ms API default. At higher
    speeds, waiting for each QoS 1 acknowledgement before publishing the next
    message would serialize network round trips and defeat speed scaling. Paho
    keeps its network loop active while messages are queued and acknowledged.
    """
    if delay_ms < 0:
        raise ValueError("A delay_ms nem lehet negatív.")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"welding-publisher-{uuid.uuid4().hex[:8]}")
    # Configure before connect; 100-150 event cycles can be in flight/queued.
    client.max_inflight_messages_set(1000)
    client.max_queued_messages_set(0)  # 0 means unbounded queue in Paho.
    client.connect(host, port, keepalive=30)
    client.loop_start()
    pending = []
    try:
        for event in events:
            outbound = dict(event)
            outbound["timestamp"] = utc_now()
            info = client.publish(EVENT_TOPIC, json.dumps(outbound, ensure_ascii=False), qos=1)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publikálási hiba a sorba állításkor: {info.rc}")
            pending.append(info)
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)

        # Use one overall timeout budget rather than giving each point a new 5 s.
        deadline = time.monotonic() + max(5.0, len(pending) * delay_ms / 1000.0 + 5.0)
        for info in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Az MQTT-események visszaigazolása túllépte a ciklus időkorlátját.")
            try:
                info.wait_for_publish(timeout=remaining)
            except RuntimeError as exc:
                raise RuntimeError(f"MQTT publikálási visszaigazolás nem érkezett meg: {exc}") from exc
            if info.rc != mqtt.MQTT_ERR_SUCCESS or not info.is_published():
                raise RuntimeError(f"MQTT publikálási hiba: {info.rc}")
    finally:
        client.loop_stop()
        client.disconnect()


# A parancssori indításkor kiválasztom a konfigurációt és elindítom az automatizált eseménygenerálást.
def main() -> None:
    configs = list_configurations()
    labels = {cfg["config_id"]: cfg["label"] for cfg in configs}
    parser = argparse.ArgumentParser(description="Excel-katalógus alapú oldalfal-hegesztési szimulátor")
    parser.add_argument("--config-id", choices=sorted(labels), default=configs[0]["config_id"])
    parser.add_argument("--fault-rate", type=float, default=0.0,
                        help="Pontonkénti hibavalószínűség (0..0.001, vagyis 0..0.1%%; alapérték 0)")
    parser.add_argument("--fault-mode", choices=FAULT_MODES, default="within_limits")
    parser.add_argument("--host", default=BROKER_HOST)
    parser.add_argument("--port", type=int, default=BROKER_PORT)
    parser.add_argument("--delay-ms", type=float, default=90.0)
    args = parser.parse_args()
    body_id, events = generate_body_events(args.config_id, args.fault_rate, fault_mode=args.fault_mode)
    publish_events(events, args.host, args.port, args.delay_ms)
    weld_events = sum(event.get("event_type") == "weld_result" for event in events)
    print(f"Elküldve: {body_id} | {labels[args.config_id]} | {weld_events} hegesztési üzenet")
    

if __name__ == "__main__":
    main()
