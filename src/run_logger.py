"""Compact, human-readable production logging: one line per body plus fault details."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_FILE_NAME = "hegesztesi_naplo.txt"


def _local_timestamp(value: Any = None) -> str:
    """Format an ISO timestamp in the computer's local time zone."""
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            else:
                parsed = parsed.astimezone()
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _append_line(log_dir: str | Path, line: str) -> Path:
    """Append one durable UTF-8 text record to the single production log."""
    target = Path(log_dir)
    target.mkdir(parents=True, exist_ok=True)
    path = target / LOG_FILE_NAME
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line.rstrip("\r\n") + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def write_weld_error_log(
    log_dir: str | Path,
    event: dict[str, Any],
    errors: list[str],
) -> Path | None:
    """Write an individual weld record only when that weld has a detected error."""
    if not errors:
        return None

    parameters = (
        f"Áram: {event.get('current_ka', '—')} kA, "
        f"idő: {event.get('weld_time_ms', '—')} ms, "
        f"elektródaerő: {event.get('electrode_force_kn', '—')} kN"
    )
    details = "; ".join(str(error) for error in errors)
    line = (
        f"{_local_timestamp(event.get('timestamp'))} | HEGESZTÉSI HIBA | "
        f"Darab: {event.get('body_id', 'ismeretlen')} | "
        f"Pont: {event.get('weld_id', 'ismeretlen')} | "
        f"Hiba: {details} | {parameters}"
    )
    return _append_line(log_dir, line)


def write_run_log(
    conn,
    body_id: str,
    config: dict[str, Any],
    expected_ids: list[str],
    received_ids: list[str],
    evaluation: dict[str, Any],
    parameter_errors: int,
    duration_seconds: float | None,
    log_dir: str | Path,
) -> Path:
    """Write exactly one summary line when a sidewall cycle is completed."""
    body = conn.execute(
        "SELECT started_at,completed_at,event_count,status FROM bodies WHERE body_id=?",
        (body_id,),
    ).fetchone()
    rework = conn.execute(
        "SELECT reason,status FROM rework_queue WHERE body_id=?",
        (body_id,),
    ).fetchone()

    expected_set = set(expected_ids)
    received_expected = len(set(received_ids) & expected_set)
    expected_count = len(expected_set)
    status = str(body["status"] if body else "ISMERETLEN")
    timestamp = body["completed_at"] if body else None
    model = " ".join(
        str(config.get(key) or "").strip()
        for key in ("brand", "model")
        if str(config.get(key) or "").strip()
    ) or str(config.get("part") or "Ismeretlen modell")

    if status == "MEGFELELŐ":
        duration = (
            f" | Ciklusidő: {float(duration_seconds):.1f} mp"
            if duration_seconds is not None else ""
        )
        line = (
            f"{_local_timestamp(timestamp)} | SIKERES HEGESZTÉS | "
            f"Darab: {body_id} | Modell: {model} | "
            f"Hegesztett pontok: {received_expected}/{expected_count}{duration}"
        )
        return _append_line(log_dir, line)

    rows = conn.execute(
        "SELECT weld_id,errors_json FROM weld_events WHERE body_id=? ORDER BY id",
        (body_id,),
    ).fetchall()
    error_points: dict[str, list[str]] = {}
    for row in rows:
        try:
            row_errors = json.loads(row["errors_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            row_errors = ["A pont hibáinak részlete nem olvasható."]
        if row_errors:
            point_id = str(row["weld_id"])
            error_points.setdefault(point_id, [])
            error_points[point_id].extend(str(item) for item in row_errors)

    def short_ids(values: Any, limit: int = 8) -> str:
        items = [str(value) for value in values or []]
        if not items:
            return "nincs"
        shown = ", ".join(items[:limit])
        return f"{shown} (+{len(items) - limit})" if len(items) > limit else shown

    problem_parts = [
        f"Hibás pontok: {len(error_points)}",
        f"Hiányzó pontok: {short_ids(evaluation.get('missing_ids', []))}",
        f"Duplikált pontok: {short_ids(evaluation.get('duplicate_ids', []))}",
        f"Váratlan pontok: {short_ids(evaluation.get('unexpected_ids', []))}",
    ]
    if parameter_errors:
        problem_parts.append(f"Paraméterhibák: {int(parameter_errors)}")
    if rework:
        problem_parts.append(f"Utómunka: {rework['status']}")
    duration = (
        f" | Ciklusidő: {float(duration_seconds):.1f} mp"
        if duration_seconds is not None else ""
    )
    line = (
        f"{_local_timestamp(timestamp)} | HIBÁS HEGESZTÉS / UTÓMUNKA | "
        f"Darab: {body_id} | Modell: {model} | "
        f"Hegesztett pontok: {received_expected}/{expected_count} | "
        f"{' | '.join(problem_parts)}{duration}"
    )
    return _append_line(log_dir, line)
