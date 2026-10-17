"""Shared speed scaling for the BODYLINE production simulator."""
from __future__ import annotations

MIN_SPEED_PERCENT = 100
MAX_SPEED_PERCENT = 10_000
DEFAULT_SPEED_PERCENT = 100


def normalize_speed_percent(value: int | float | str) -> int:
    """Normalize a UI/config value to the supported 100%-10,000% range."""
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("A sebességnek számnak kell lennie.") from exc
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise ValueError("A sebességnek véges számnak kell lennie.")
    return max(MIN_SPEED_PERCENT, min(MAX_SPEED_PERCENT, int(round(numeric))))


def scaled_publish_delay_ms(base_delay_ms: float, speed_percent: int | float) -> float:
    """Scale the pause between MQTT messages; 100% preserves the existing baseline."""
    if base_delay_ms < 0:
        raise ValueError("Az alap küldési késleltetés nem lehet negatív.")
    speed = normalize_speed_percent(speed_percent)
    return float(base_delay_ms) * MIN_SPEED_PERCENT / speed


def scaled_inter_body_pause_seconds(base_pause_seconds: float, speed_percent: int | float) -> float:
    """Scale the idle pause between bodies; 100% preserves the existing baseline."""
    if base_pause_seconds < 0:
        raise ValueError("Az alap karosszéria-szünet nem lehet negatív.")
    speed = normalize_speed_percent(speed_percent)
    return float(base_pause_seconds) * MIN_SPEED_PERCENT / speed
