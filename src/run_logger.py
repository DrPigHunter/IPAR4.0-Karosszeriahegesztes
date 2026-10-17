"""JSON run logs and aggregate production statistics for completed sidewall cycles."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.speed_control import CYCLE_TARGET_SECONDS


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
    """Write one JSON report per completed body and update JSONL/aggregate logs."""
    target = Path(log_dir)
    target.mkdir(parents=True, exist_ok=True)
    body = conn.execute(
        "SELECT started_at,completed_at,event_count,status FROM bodies WHERE body_id=?",
        (body_id,),
    ).fetchone()
    rework = conn.execute(
        "SELECT reason,status FROM rework_queue WHERE body_id=?",
        (body_id,),
    ).fetchone()

    received_set = set(received_ids)
    expected_set = set(expected_ids)
    received_expected = len(received_set & expected_set)
    expected_count = len(expected_set)
    now = datetime.now(timezone.utc)
    report = {
        "record_type": "completed_sidewall_run",
        "logged_at": now.isoformat(),
        "body_id": body_id,
        "config_id": config["config_id"],
        "manufacturer": config["brand"],
        "model": config["model"],
        "part": config["part"],
        "expected_weld_points": expected_count,
        "received_unique_expected_points": received_expected,
        "event_count": int(body["event_count"] if body else 0),
        "point_completeness_percent": round(100.0 * received_expected / expected_count, 2) if expected_count else 0.0,
        "parameter_error_count": int(parameter_errors),
        "missing_point_ids": evaluation.get("missing_ids", []),
        "unexpected_point_ids": evaluation.get("unexpected_ids", []),
        "duplicate_point_ids": evaluation.get("duplicate_ids", []),
        "status": str(body["status"] if body else "ISMERETLEN"),
        "rework_required": rework is not None,
        "rework_reason": str(rework["reason"]) if rework else "",
        "rework_status": str(rework["status"]) if rework else "",
        "started_at": str(body["started_at"]) if body else "",
        "completed_at": str(body["completed_at"]) if body else "",
        "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
        "within_100_second_target": bool(
            duration_seconds is not None and duration_seconds < CYCLE_TARGET_SECONDS
        ),
        "target_cycle_seconds": CYCLE_TARGET_SECONDS,
    }

    stamp = now.strftime("%Y%m%d_%H%M%S_%f")
    individual_path = target / f"run_{stamp}_{body_id}.json"
    individual_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    daily_path = target / f"production_{now.strftime('%Y-%m-%d')}.jsonl"
    with daily_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False) + "\n")

    completed = conn.execute(
        "SELECT status,duration_seconds FROM bodies WHERE status!='FOLYAMATBAN'"
    ).fetchall()
    total = len(completed)
    passed = sum(1 for row in completed if row["status"] == "MEGFELELŐ")
    rework_count = sum(1 for row in completed if "SELEJT" in str(row["status"]))
    durations = [float(row["duration_seconds"]) for row in completed if row["duration_seconds"] is not None]
    summary = {
        "updated_at": now.isoformat(),
        "completed_sidewalls_total": total,
        "passed_sidewalls_total": passed,
        "rework_sidewalls_total": rework_count,
        "pass_rate_percent": round(100.0 * passed / total, 2) if total else 0.0,
        "rework_rate_percent": round(100.0 * rework_count / total, 2) if total else 0.0,
        "average_cycle_seconds": round(sum(durations) / len(durations), 3) if durations else None,
        "cycle_target_seconds": CYCLE_TARGET_SECONDS,
        "note": "Historical summary includes earlier runs from the SQLite database; compare individual JSON logs for current-cycle results.",
    }
    summary_path = target / "production_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return individual_path
