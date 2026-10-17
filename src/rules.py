"""Validation rules for simulated spot-welding events."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Limits:
    current_min: float = 7.0
    current_max: float = 11.0
    weld_time_min: float = 150.0
    weld_time_max: float = 350.0
    force_min: float = 2.5
    force_max: float = 4.5

DEFAULT_LIMITS = Limits()

def validate_event(event: dict[str, Any], limits: Limits = DEFAULT_LIMITS) -> list[str]:
    """Return human-readable deviations for one weld result event."""
    errors: list[str] = []
    checks = (("current_ka", limits.current_min, limits.current_max, "Áramerősség"), ("weld_time_ms", limits.weld_time_min, limits.weld_time_max, "Hegesztési idő"), ("electrode_force_kn", limits.force_min, limits.force_max, "Elektródaerő"))
    for key, low, high, label in checks:
        value = event.get(key)
        if not isinstance(value, (int, float)):
            errors.append(f"{label}: hiányzó vagy nem numerikus érték")
        elif not low <= float(value) <= high:
            errors.append(f"{label}: {value} kívül esik a [{low}, {high}] tartományon")
    return errors

def evaluate_body(expected_ids: list[str], received_ids: list[str], parameter_errors: int) -> dict[str, Any]:
    """Evaluate completeness and duplicate IDs for a completed simulated body."""
    expected, received = set(expected_ids), set(received_ids)
    missing = sorted(expected - received)
    unexpected = sorted(received - expected)
    seen: set[str] = set()
    duplicates: set[str] = set()
    for point_id in received_ids:
        if point_id in seen:
            duplicates.add(point_id)
        seen.add(point_id)
    ok = not missing and not unexpected and not duplicates and parameter_errors == 0
    return {"status": "MEGFELELŐ" if ok else "SELEJT / ELLENŐRIZENDŐ", "missing_ids": missing, "unexpected_ids": unexpected, "duplicate_ids": sorted(duplicates), "parameter_errors": parameter_errors}
