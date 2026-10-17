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

DEFAULT_FAULT_RATE = 0.0

# These are deliberately not exposed as UI inputs.
FACTORY_EQUIPMENT_SETTINGS: dict[str, Any] = {
    "fault_rate": DEFAULT_FAULT_RATE,
    "fault_mode": "within_limits",
    "wear_enabled": True,
    "wear_per_point_percent": DEFAULT_WEAR_PER_POINT_PERCENT,
    "auto_correct_wear": True,
    "auto_tool_change_enabled": True,
    "tool_change_interval_bodies": DEFAULT_TOOL_CHANGE_INTERVAL_BODIES,
    "tool_change_duration_seconds": DEFAULT_TOOL_CHANGE_DURATION_SECONDS,
    "coolant_flow_l_min": COATED_STEEL_COOLANT_FLOW_TARGET_L_MIN,
    "coolant_inlet_temp_c": COOLANT_INLET_TARGET_MAX_C,
    "coolant_outlet_temp_c": COOLANT_OUTLET_TARGET_MAX_C,
}


def apply_factory_settings(state: MutableMapping[str, Any]) -> None:
    """Replace saved/legacy process settings with the code-defined defaults."""
    state.update(FACTORY_EQUIPMENT_SETTINGS)
