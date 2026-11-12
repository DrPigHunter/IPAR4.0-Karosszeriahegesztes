"""Shared speed scaling for the BODYLINE production simulator."""
from __future__ import annotations

import math

MIN_SPEED_PERCENT = 100
MAX_SPEED_PERCENT = 10_000
DEFAULT_SPEED_PERCENT = 100
DEFAULT_TARGET_CYCLE_SECONDS = 95.0
CYCLE_TARGET_SECONDS = 100


# A kezelőfelületről érkező értéket a támogatott 100–10 000%-os tartományra ellenőrzöm és normalizálom.
def normalize_speed_percent(value: int | float | str) -> int:
    """Normalize a UI/config value to the supported 100%-10,000% range."""
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("A sebességnek számnak kell lennie.") from exc
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise ValueError("A sebességnek véges számnak kell lennie.")
    return max(MIN_SPEED_PERCENT, min(MAX_SPEED_PERCENT, int(round(numeric))))


# A modell pontszámából számolom ki az alap eseményközt úgy, hogy a teljes pontsor névlegesen 95 másodperces legyen.
def base_publish_delay_ms(
    event_count: int,
    target_cycle_seconds: float = DEFAULT_TARGET_CYCLE_SECONDS,
) -> float:
    """Return a per-event pause that paces the complete event stream to a target cycle."""
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count <= 0:
        raise ValueError("Az eseményszámnak pozitív egész számnak kell lennie.")
    if not math.isfinite(target_cycle_seconds) or target_cycle_seconds <= 0:
        raise ValueError("A cél ciklusidőnek pozitív, véges számnak kell lennie.")
    return float(target_cycle_seconds) * 1000.0 / event_count


# A névleges eseményközt a kiválasztott szimulációs sebesség alapján skálázom.
def scaled_publish_delay_ms(base_delay_ms: float, speed_percent: int | float) -> float:
    """Scale the pause between MQTT messages; 100% preserves the existing baseline."""
    if base_delay_ms < 0:
        raise ValueError("Az alap küldési késleltetés nem lehet negatív.")
    speed = normalize_speed_percent(speed_percent)
    return float(base_delay_ms) * MIN_SPEED_PERCENT / speed


# A két oldalfal közötti szünetet is a sebességhez igazítom, külön kezelve a pontok küldési idejétől.
def scaled_inter_body_pause_seconds(base_pause_seconds: float, speed_percent: int | float) -> float:
    """Scale the idle pause between bodies; 100% preserves the existing baseline."""
    if base_pause_seconds < 0:
        raise ValueError("Az alap karosszéria-szünet nem lehet negatív.")
    speed = normalize_speed_percent(speed_percent)
    return float(base_pause_seconds) * MIN_SPEED_PERCENT / speed
