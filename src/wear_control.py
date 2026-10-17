"""Educational electrode-wear model and bounded automatic process compensation.

This is a synthetic simulation model, not a validated welding recipe.  The
controller may adjust only within the model-specific limits from the catalog.
If those limits cannot restore the simulated quality index, the weld event is
explicitly flagged so the monitor routes the body to rework.
"""
from __future__ import annotations

from typing import Any, MutableMapping

QUALITY_TARGET_PERCENT = 95.0
WEAR_HEAT_LOSS_PER_PERCENT = 0.0025  # 0.25% heat proxy loss per 1% electrode wear
CURRENT_STEP_KA = 0.05
WELD_TIME_STEP_MS = 2.0
MAX_CORRECTION_STEPS = 80


def _quality_index(event: dict[str, Any], point: dict[str, Any], wear_percent: float) -> float:
    """Return a synthetic heat/quality proxy from current, time and electrode wear."""
    nominal_current = max(float(point["nominal_current_ka"]), 0.001)
    nominal_time = max(float(point["nominal_weld_time_ms"]), 0.001)
    wear_factor = max(0.0, 1.0 - wear_percent * WEAR_HEAT_LOSS_PER_PERCENT)
    ratio = (
        float(event["current_ka"]) / nominal_current
        * float(event["weld_time_ms"]) / nominal_time
        * wear_factor
    )
    return round(100.0 * ratio, 2)


def apply_electrode_wear(
    events: list[dict[str, Any]],
    config: dict[str, Any],
    wear_state: MutableMapping[str, Any] | None = None,
    *,
    wear_per_point_percent: float = 0.03,
    wear_enabled: bool = True,
    auto_correct: bool = True,
) -> dict[str, Any]:
    """Apply cumulative synthetic wear and bounded feedback correction to weld events.

    The mutable wear_state is intentionally shared between cycles by the dashboard,
    so wear accumulates during one run. Parameters are clamped to catalog limits.
    A weld that remains below QUALITY_TARGET_PERCENT after all allowed corrections
    is flagged as process_quality_ok=False; the monitor must send its body to rework.
    """
    if not 0.0 <= float(wear_per_point_percent) <= 1.0:
        raise ValueError("A pontonkénti elektróda-kopás 0 és 1 százalék közé essen.")
    state: MutableMapping[str, Any] = wear_state if wear_state is not None else {}
    state.setdefault("wear_percent", 0.0)
    state.setdefault("total_weld_points", 0)
    state.setdefault("corrected_points", 0)
    state.setdefault("correction_steps", 0)
    state.setdefault("uncorrectable_points", 0)

    limits = config["limits"]
    point_by_id = {str(point["weld_id"]): point for point in config["points"]}
    cycle_corrections = 0
    cycle_steps = 0
    cycle_uncorrectable = 0
    cycle_weld_points = 0

    for event in events:
        if event.get("event_type") != "weld_result":
            continue
        point = point_by_id.get(str(event.get("weld_id")))
        if point is None:
            continue

        if wear_enabled:
            state["wear_percent"] = min(
                100.0,
                max(0.0, float(state["wear_percent"]) + float(wear_per_point_percent)),
            )
        wear_percent = round(float(state["wear_percent"]), 3)
        quality_wear_percent = wear_percent if wear_enabled else 0.0
        current_before = float(event["current_ka"])
        time_before = float(event["weld_time_ms"])
        quality_before = _quality_index(event, point, quality_wear_percent)
        steps = 0
        actions: list[str] = []

        if wear_enabled and auto_correct:
            while quality_before < QUALITY_TARGET_PERCENT and steps < MAX_CORRECTION_STEPS:
                current = float(event["current_ka"])
                weld_time = float(event["weld_time_ms"])
                if current + CURRENT_STEP_KA <= float(limits.current_max) + 1e-9:
                    event["current_ka"] = round(min(float(limits.current_max), current + CURRENT_STEP_KA), 2)
                    actions.append("áramerősség emelése")
                elif weld_time + WELD_TIME_STEP_MS <= float(limits.weld_time_max) + 1e-9:
                    event["weld_time_ms"] = round(min(float(limits.weld_time_max), weld_time + WELD_TIME_STEP_MS), 1)
                    actions.append("hegesztési idő növelése")
                else:
                    break
                steps += 1
                quality_before = _quality_index(event, point, quality_wear_percent)

        quality_after = _quality_index(event, point, quality_wear_percent)
        corrected = steps > 0 and quality_after >= QUALITY_TARGET_PERCENT
        quality_ok = quality_after >= QUALITY_TARGET_PERCENT

        event.update({
            "electrode_wear_enabled": bool(wear_enabled),
            "electrode_wear_percent": wear_percent,
            "simulated_quality_index_percent": quality_after,
            "quality_index_before_correction_percent": _quality_index(
                {"current_ka": current_before, "weld_time_ms": time_before}, point, quality_wear_percent
            ),
            "process_quality_ok": bool(quality_ok),
            "auto_correction_enabled": bool(auto_correct and wear_enabled),
            "auto_correction_applied": bool(corrected),
            "auto_correction_steps": int(steps),
            "auto_correction_actions": " → ".join(dict.fromkeys(actions)) if actions else "nincs",
            "wear_quality_status": (
                "KORRIGÁLVA" if corrected else
                "MEGFELELŐ" if quality_ok else
                "KORREKCIÓ SIKERTELEN"
            ),
        })

        cycle_weld_points += 1
        state["total_weld_points"] = int(state["total_weld_points"]) + 1
        if corrected:
            cycle_corrections += 1
            state["corrected_points"] = int(state["corrected_points"]) + 1
        if steps:
            cycle_steps += steps
            state["correction_steps"] = int(state["correction_steps"]) + steps
        if not quality_ok:
            cycle_uncorrectable += 1
            state["uncorrectable_points"] = int(state["uncorrectable_points"]) + 1

    return {
        "wear_enabled": bool(wear_enabled),
        "auto_correct_enabled": bool(auto_correct and wear_enabled),
        "wear_percent": round(float(state["wear_percent"]), 3),
        "weld_points": cycle_weld_points,
        "corrected_points": cycle_corrections,
        "correction_steps": cycle_steps,
        "uncorrectable_points": cycle_uncorrectable,
        "quality_target_percent": QUALITY_TARGET_PERCENT,
    }
