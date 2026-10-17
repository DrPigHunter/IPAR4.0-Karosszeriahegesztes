"""Educational electrode-wear model and bounded automatic process compensation.

This is a synthetic simulation model, not a validated welding recipe.  The
controller may adjust only within the model-specific limits from the catalog.
If those limits cannot restore the simulated quality index, the weld event is
explicitly flagged so the monitor routes the body to rework.
"""
from __future__ import annotations

from typing import Any, MutableMapping

QUALITY_TARGET_PERCENT = 95.0  # Demonstration threshold, not an industry acceptance standard.
WEAR_HEAT_LOSS_PER_PERCENT = 0.0025  # Synthetic wear penalty; requires calibration against real trials.
CURRENT_STEP_KA = 0.10  # 0.1 kA current-stepping increment, consistent with a weld-lobe style adjustment scale.
WELD_TIME_STEP_MS = 5.0
MAX_CORRECTION_STEPS = 80
DEFAULT_WEAR_PER_POINT_PERCENT = 0.005
DEFAULT_TOOL_CHANGE_INTERVAL_BODIES = 100
MIN_TOOL_CHANGE_INTERVAL_BODIES = 1
MAX_TOOL_CHANGE_INTERVAL_BODIES = 10_000
DEFAULT_TOOL_CHANGE_DURATION_SECONDS = 5.0
MIN_TOOL_CHANGE_DURATION_SECONDS = 0.5
MAX_TOOL_CHANGE_DURATION_SECONDS = 300.0
COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN = 6.0
COOLANT_INLET_TARGET_MAX_C = 20.0
COOLANT_OUTLET_TARGET_MAX_C = 30.0


def ensure_wear_state(state: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Initialize lifetime and current-tool counters without discarding old state."""
    defaults = {
        "wear_percent": 0.0,
        "total_weld_points": 0,
        "corrected_points": 0,
        "correction_steps": 0,
        "uncorrectable_points": 0,
        "current_tool_number": 1,
        "tool_change_count": 0,
        "bodies_since_tool_change": 0,
        "tool_weld_points": 0,
        "tool_corrected_points": 0,
        "tool_correction_steps": 0,
        "tool_uncorrectable_points": 0,
        "tool_change_pending": False,
        "pending_tool_change_body_id": "",
    }
    for key, value in defaults.items():
        state.setdefault(key, value)
    return state


def _validate_tool_change_interval(interval_bodies: int) -> int:
    if isinstance(interval_bodies, bool) or not isinstance(interval_bodies, int):
        raise ValueError("Az automatikus eszközcsere-intervallumnak egész karosszériadarab-számnak kell lennie.")
    if not MIN_TOOL_CHANGE_INTERVAL_BODIES <= interval_bodies <= MAX_TOOL_CHANGE_INTERVAL_BODIES:
        raise ValueError(
            f"Az eszközcsere-intervallum {MIN_TOOL_CHANGE_INTERVAL_BODIES} és "
            f"{MAX_TOOL_CHANGE_INTERVAL_BODIES} karosszéria között állítható."
        )
    return interval_bodies


def replace_electrode_tool(
    wear_state: MutableMapping[str, Any],
    *,
    reason: str = "MANUAL",
    body_id: str | None = None,
) -> dict[str, Any]:
    """Register a tool/electrode replacement and reset only the new tool's wear."""
    state = ensure_wear_state(wear_state)
    previous_tool_number = int(state["current_tool_number"])
    change = {
        "change_mode": str(reason),
        "completed_body_id": body_id or "",
        "previous_tool_number": previous_tool_number,
        "new_tool_number": previous_tool_number + 1,
        "tool_change_number": int(state["tool_change_count"]) + 1,
        "bodies_since_previous_change": int(state["bodies_since_tool_change"]),
        "wear_percent_before_reset": round(float(state["wear_percent"]), 3),
        "wear_percent_after_reset": 0.0,
        "tool_weld_points_before_reset": int(state["tool_weld_points"]),
        "tool_corrected_points_before_reset": int(state["tool_corrected_points"]),
        "tool_uncorrectable_points_before_reset": int(state["tool_uncorrectable_points"]),
    }
    state["current_tool_number"] = change["new_tool_number"]
    state["tool_change_count"] = change["tool_change_number"]
    state["bodies_since_tool_change"] = 0
    state["wear_percent"] = 0.0
    state["tool_weld_points"] = 0
    state["tool_corrected_points"] = 0
    state["tool_correction_steps"] = 0
    state["tool_uncorrectable_points"] = 0
    state["tool_change_pending"] = False
    state["pending_tool_change_body_id"] = ""
    state["last_tool_change"] = dict(change)
    return change


def replace_tool_if_due(
    wear_state: MutableMapping[str, Any],
    interval_bodies: int = DEFAULT_TOOL_CHANGE_INTERVAL_BODIES,
    *,
    enabled: bool = True,
    body_id: str | None = None,
) -> dict[str, Any] | None:
    """Replace before the next cycle if the configured body-life limit is already met."""
    interval = _validate_tool_change_interval(interval_bodies)
    state = ensure_wear_state(wear_state)
    if enabled and (
        bool(state.get("tool_change_pending"))
        or int(state["bodies_since_tool_change"]) >= interval
    ):
        return replace_electrode_tool(
            state,
            reason="AUTO_DURING_BREAK",
            body_id=body_id or str(state.get("pending_tool_change_body_id") or ""),
        )
    return None


def register_completed_body_for_tool(
    wear_state: MutableMapping[str, Any],
    interval_bodies: int = DEFAULT_TOOL_CHANGE_INTERVAL_BODIES,
    *,
    enabled: bool = True,
    body_id: str | None = None,
) -> dict[str, Any] | None:
    """Count one finalized sidewall cycle and schedule replacement at the next break.

    This function never resets the tool immediately. The worker uses the following
    inter-body pause to perform the replacement; when automatic replacement is
    disabled, it flags a manual-maintenance stop.
    """
    interval = _validate_tool_change_interval(interval_bodies)
    state = ensure_wear_state(wear_state)
    state["bodies_since_tool_change"] = int(state["bodies_since_tool_change"]) + 1
    if int(state["bodies_since_tool_change"]) >= interval:
        state["tool_change_pending"] = True
        state["pending_tool_change_body_id"] = body_id or ""
        return {
            "change_mode": "PENDING_AUTO" if enabled else "PENDING_MANUAL",
            "completed_body_id": body_id or "",
            "previous_tool_number": int(state["current_tool_number"]),
            "new_tool_number": int(state["current_tool_number"]) + 1,
            "bodies_since_previous_change": int(state["bodies_since_tool_change"]),
            "wear_percent_before_reset": round(float(state["wear_percent"]), 3),
            "pending": True,
        }
    return None


def _quality_index(
    event: dict[str, Any],
    point: dict[str, Any],
    wear_percent: float,
    *,
    cooling_stress_factor: float = 1.0,
) -> float:
    """Return a synthetic relative Joule-heat proxy, not a weld-strength prediction.

    The electrical component uses I^2 * t * R as the physically grounded baseline.
    Electrode wear and coolant stress are simplified empirical multipliers that must
    be calibrated from process trials before any industrial use.
    """
    nominal_current = max(float(point["nominal_current_ka"]), 0.001)
    nominal_time = max(float(point["nominal_weld_time_ms"]), 0.001)
    wear_factor = max(0.0, 1.0 - wear_percent * WEAR_HEAT_LOSS_PER_PERCENT)
    ratio = (
        (float(event["current_ka"]) / nominal_current) ** 2
        * (float(event["weld_time_ms"]) / nominal_time)
        * wear_factor
        / max(1.0, cooling_stress_factor)
    )
    return round(100.0 * ratio, 2)


def cooling_condition(
    coolant_flow_l_min: float = COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN,
    coolant_inlet_temp_c: float = COOLANT_INLET_TARGET_MAX_C,
    coolant_outlet_temp_c: float = COOLANT_OUTLET_TARGET_MAX_C,
) -> dict[str, Any]:
    """Estimate cooling risk against TWI recommendations for coated/thicker steel.

    The alert thresholds come from TWI guidance. The numerical wear penalty is a
    transparent simulation heuristic, not a validated thermal model.
    """
    flow = float(coolant_flow_l_min)
    inlet = float(coolant_inlet_temp_c)
    outlet = float(coolant_outlet_temp_c)
    if flow < 0.0 or flow > 30.0:
        raise ValueError("A hűtővíz térfogatáramának 0 és 30 l/perc között kell lennie.")
    if not -10.0 <= inlet <= 80.0 or not -10.0 <= outlet <= 100.0:
        raise ValueError("A hűtővíz-hőmérsékleti beállítás kívül esik a szimulációs tartományon.")

    alerts: list[str] = []
    if flow < COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN:
        alerts.append(
            f"Alacsony hűtővíz-áramlás: {flow:.1f} l/perc; "
            f"bevonatos/vastagabb acél referenciaértéke legalább "
            f"{COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN:.1f} l/perc."
        )
    if inlet > COOLANT_INLET_TARGET_MAX_C:
        alerts.append(f"A hűtővíz belépő hőmérséklete magas ({inlet:.1f} °C; referencia max. 20 °C).")
    if outlet > COOLANT_OUTLET_TARGET_MAX_C:
        alerts.append(f"A hűtővíz kilépő hőmérséklete magas ({outlet:.1f} °C; referencia max. 30 °C).")

    low_flow_stress = max(0.0, (COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN - flow) / COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN)
    inlet_stress = max(0.0, inlet - COOLANT_INLET_TARGET_MAX_C) / 20.0
    outlet_stress = max(0.0, outlet - COOLANT_OUTLET_TARGET_MAX_C) / 20.0
    stress_factor = 1.0 + 1.5 * low_flow_stress + 0.25 * inlet_stress + 0.5 * outlet_stress
    return {
        "flow_l_min": round(flow, 3),
        "inlet_temp_c": round(inlet, 2),
        "outlet_temp_c": round(outlet, 2),
        "alerts": alerts,
        "wear_stress_factor": round(stress_factor, 3),
    }


def apply_electrode_wear(
    events: list[dict[str, Any]],
    config: dict[str, Any],
    wear_state: MutableMapping[str, Any] | None = None,
    *,
    wear_per_point_percent: float = DEFAULT_WEAR_PER_POINT_PERCENT,
    wear_enabled: bool = True,
    auto_correct: bool = True,
    coolant_flow_l_min: float = COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN,
    coolant_inlet_temp_c: float = COOLANT_INLET_TARGET_MAX_C,
    coolant_outlet_temp_c: float = COOLANT_OUTLET_TARGET_MAX_C,
) -> dict[str, Any]:
    """Apply cumulative synthetic wear and bounded feedback correction to weld events.

    The mutable wear_state is intentionally shared between cycles by the dashboard,
    so wear accumulates during one run. Parameters are clamped to catalog limits.
    A weld that remains below QUALITY_TARGET_PERCENT after all allowed corrections
    is flagged as process_quality_ok=False; the monitor must send its body to rework.
    """
    if not 0.0 <= float(wear_per_point_percent) <= 0.1:
        raise ValueError("A pontonkénti szimulált kopás 0 és 0,1% közé essen.")
    cooling = cooling_condition(coolant_flow_l_min, coolant_inlet_temp_c, coolant_outlet_temp_c)
    state: MutableMapping[str, Any] = wear_state if wear_state is not None else {}
    ensure_wear_state(state)

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

        effective_wear_increment = (
            float(wear_per_point_percent) * float(cooling["wear_stress_factor"])
            if wear_enabled else 0.0
        )
        if wear_enabled:
            state["wear_percent"] = min(
                100.0,
                max(0.0, float(state["wear_percent"]) + effective_wear_increment),
            )
        wear_percent = round(float(state["wear_percent"]), 3)
        quality_wear_percent = wear_percent if wear_enabled else 0.0
        current_before = float(event["current_ka"])
        time_before = float(event["weld_time_ms"])
        quality_before = _quality_index(
            event, point, quality_wear_percent,
            cooling_stress_factor=float(cooling["wear_stress_factor"]),
        )
        steps = 0
        actions: list[str] = []

        if wear_enabled and auto_correct and event.get("simulated_variation") != "OUTSIDE_ACCEPTED_LIMITS":
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
                quality_before = _quality_index(
                    event, point, quality_wear_percent,
                    cooling_stress_factor=float(cooling["wear_stress_factor"]),
                )

        quality_after = _quality_index(
            event, point, quality_wear_percent,
            cooling_stress_factor=float(cooling["wear_stress_factor"]),
        )
        corrected = steps > 0 and quality_after >= QUALITY_TARGET_PERCENT
        quality_ok = quality_after >= QUALITY_TARGET_PERCENT

        event.update({
            "electrode_wear_enabled": bool(wear_enabled),
            "electrode_tool_number": int(state["current_tool_number"]),
            "electrode_wear_percent": wear_percent,
            "wear_increment_percent": round(effective_wear_increment, 5),
            "coolant_flow_l_min": cooling["flow_l_min"],
            "coolant_inlet_temp_c": cooling["inlet_temp_c"],
            "coolant_outlet_temp_c": cooling["outlet_temp_c"],
            "cooling_alerts": list(cooling["alerts"]),
            "cooling_stress_factor": cooling["wear_stress_factor"],
            "simulated_quality_index_percent": quality_after,
            "quality_index_before_correction_percent": _quality_index(
                {"current_ka": current_before, "weld_time_ms": time_before}, point, quality_wear_percent,
                cooling_stress_factor=float(cooling["wear_stress_factor"]),
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

        event["electrode_tool_number"] = int(state["current_tool_number"])
        cycle_weld_points += 1
        state["total_weld_points"] = int(state["total_weld_points"]) + 1
        state["tool_weld_points"] = int(state["tool_weld_points"]) + 1
        if corrected:
            cycle_corrections += 1
            state["corrected_points"] = int(state["corrected_points"]) + 1
            state["tool_corrected_points"] = int(state["tool_corrected_points"]) + 1
        if steps:
            cycle_steps += steps
            state["correction_steps"] = int(state["correction_steps"]) + steps
            state["tool_correction_steps"] = int(state["tool_correction_steps"]) + steps
        if not quality_ok:
            cycle_uncorrectable += 1
            state["uncorrectable_points"] = int(state["uncorrectable_points"]) + 1
            state["tool_uncorrectable_points"] = int(state["tool_uncorrectable_points"]) + 1

    return {
        "wear_enabled": bool(wear_enabled),
        "auto_correct_enabled": bool(auto_correct and wear_enabled),
        "wear_percent": round(float(state["wear_percent"]), 3),
        "current_tool_number": int(state["current_tool_number"]),
        "tool_change_count": int(state["tool_change_count"]),
        "bodies_since_tool_change": int(state["bodies_since_tool_change"]),
        "tool_change_pending": bool(state.get("tool_change_pending")),
        "cooling": cooling,
        "weld_points": cycle_weld_points,
        "corrected_points": cycle_corrections,
        "correction_steps": cycle_steps,
        "uncorrectable_points": cycle_uncorrectable,
        "quality_target_percent": QUALITY_TARGET_PERCENT,
    }
