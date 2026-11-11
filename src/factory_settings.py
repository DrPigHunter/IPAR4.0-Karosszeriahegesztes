"""Code-only factory defaults for the welding simulation.

Operators may change only simulation speed in the dashboard. Change these values
in source control when the teaching/demo configuration needs to be adjusted.
These are simulation defaults, not a certified industrial welding recipe.
"""
from __future__ import annotations

from typing import Any, MutableMapping

from src.wear_control import (
    COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN,
    COOLANT_INLET_TARGET_MAX_C,
    COOLANT_OUTLET_TARGET_MAX_C,
    DEFAULT_TOOL_CHANGE_DURATION_SECONDS,
    DEFAULT_TOOL_CHANGE_INTERVAL_BODIES,
    DEFAULT_WEAR_PER_POINT_PERCENT,
)

DEFAULT_FAULT_RATE = 0.0  # Deliberate test fault injection; off by default.

# Synthetic background failure probability independent of electrode wear:
# 0.01% per weld point (1 in 10,000). This is a demo assumption, NOT an
# industry-wide measured defect rate. See docs/parameter_realism_audit.md.
DEFAULT_NON_WEAR_DEFECT_PROBABILITY = 0.0001

# One simulated shift-break checkpoint per 100 completed sidewalls. With roughly
# 140 weld points per sidewall this is ~14,000 weld points, near the order of
# magnitude discussed by the CORDIS SmartDress development target. This is a
# simulation cadence, not a universal real-world shift or electrode-life rule.
SHIFT_BREAK_INTERVAL_BODIES = DEFAULT_TOOL_CHANGE_INTERVAL_BODIES
SHIFT_BREAK_APPROX_WELD_POINTS = 14_000

# These are deliberately not exposed as UI inputs.
FACTORY_EQUIPMENT_SETTINGS: dict[str, Any] = {
    "fault_rate": DEFAULT_FAULT_RATE,
    "non_wear_defect_probability": DEFAULT_NON_WEAR_DEFECT_PROBABILITY,
    "fault_mode": "within_limits",
    "wear_enabled": True,
    "wear_per_point_percent": DEFAULT_WEAR_PER_POINT_PERCENT,
    "auto_correct_wear": True,
    "auto_tool_change_enabled": True,
    "tool_change_interval_bodies": SHIFT_BREAK_INTERVAL_BODIES,
    "tool_change_duration_seconds": DEFAULT_TOOL_CHANGE_DURATION_SECONDS,
    "coolant_flow_l_min": COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN,
    "coolant_inlet_temp_c": COOLANT_INLET_TARGET_MAX_C,
    "coolant_outlet_temp_c": COOLANT_OUTLET_TARGET_MAX_C,
}


# A kódban rögzített oktatási alapbeállításokat alkalmazom; ezek nem minősített ipari hegesztési receptek.
def apply_factory_settings(state: MutableMapping[str, Any]) -> None:
    """Replace saved/legacy process settings with the code-defined defaults.

    The head/ electrode assembly is replaced after the configured number of
    sidewalls, during the following simulated downtime window.
    """
    state.update(FACTORY_EQUIPMENT_SETTINGS)
