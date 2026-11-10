"""Durable state for the simulated welding electrode/tool between dashboard restarts."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EQUIPMENT_STATE_PATH = ROOT / "data" / "equipment_state.json"

STATE_FIELDS = (
    "wear_state",
    "wear_enabled",
    "wear_per_point_percent",
    "auto_correct_wear",
    "auto_tool_change_enabled",
    "tool_change_interval_bodies",
    "tool_change_duration_seconds",
    "coolant_flow_l_min",
    "coolant_inlet_temp_c",
    "coolant_outlet_temp_c",
)


# A tartós fájlból visszaállítom az elektróda és az eszköz állapotát, hogy egy dashboard-újraindítás ne nullázza le a kopást.
def load_equipment_state(path: str | Path = DEFAULT_EQUIPMENT_STATE_PATH) -> dict[str, Any]:
    """Load known wear/tool settings; reject malformed persisted data safely."""
    state_path = Path(path)
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    result = {key: value[key] for key in STATE_FIELDS if key in value}
    wear_state = result.get("wear_state")
    if wear_state is not None and not isinstance(wear_state, dict):
        result.pop("wear_state", None)
    return result


# Biztonságosan, ideiglenes fájlon keresztül mentem az állapotot, hogy félbeszakadt íráskor se maradjon sérült JSON.
def save_equipment_state(
    state: Mapping[str, Any],
    path: str | Path = DEFAULT_EQUIPMENT_STATE_PATH,
) -> Path:
    """Atomically save equipment life counters/settings so restarts do not reset wear."""
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: state[key] for key in STATE_FIELDS if key in state}
    # Convert nested counters to JSON-safe built-ins and avoid storing dashboard objects.
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{state_path.stem}-", suffix=".tmp", dir=str(state_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, state_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return state_path
