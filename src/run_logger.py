"""English, human-readable production log: lifecycle events per part and weld faults."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_FILE_NAME = "production_log.txt"


# A naplóbejegyzéseket a számítógép helyi időzónájában jelenítem meg, hogy a kezelő a saját órájával tudja összevetni.
def _local_timestamp(value: Any = None) -> str:
    """Format an ISO timestamp in the computer's local time zone."""
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OverflowError):
            pass
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


# Egyetlen naplóbejegyzést fűzök a fájl végére, és azonnal kiíratom a pufferből.
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


# A katalógusrekordból ember által olvasható gyártó- és modellnevet állítok elő.
def _model_name(config: dict[str, Any]) -> str:
    return " ".join(
        str(config.get(key) or "").strip()
        for key in ("brand", "model")
        if str(config.get(key) or "").strip()
    ) or str(config.get("label") or "Unknown model")


# A belső hibaüzeneteket rövid, egységes angol megfogalmazásra alakítom a production TXT naplóban.
def _english_error(error: Any) -> str:
    """Translate validation messages into stable English log descriptions."""
    message = str(error)
    if message.startswith("Áramerősség:"):
        detail = message.split(":", 1)[1].strip()
        if detail.startswith("hiányzó vagy nem numerikus érték"):
            return "Current: missing or non-numeric value"
        return f"Current: {detail.replace('kívül esik a', 'is outside the').replace('tartományon', 'range')}"
    if message.startswith("Hegesztési idő:"):
        detail = message.split(":", 1)[1].strip()
        if detail.startswith("hiányzó vagy nem numerikus érték"):
            return "Weld time: missing or non-numeric value"
        return f"Weld time: {detail.replace('kívül esik a', 'is outside the').replace('tartományon', 'range')}"
    if message.startswith("Elektródaerő:"):
        detail = message.split(":", 1)[1].strip()
        if detail.startswith("hiányzó vagy nem numerikus érték"):
            return "Electrode force: missing or non-numeric value"
        return f"Electrode force: {detail.replace('kívül esik a', 'is outside the').replace('tartományon', 'range')}"
    if message.startswith("Elektródakopás miatti minőségi eltérés:"):
        return "Electrode wear-related quality deviation: automatic correction did not reach the simulated target within permitted limits."
    if message.startswith("Váratlan hegesztési pont:"):
        return "Unexpected weld point: not listed in the configured weld-point catalog."
    if message.startswith("Duplikált üzenet:"):
        return "Duplicate weld event: this point had already been received."
    return "Weld validation fault: an unclassified validation error was detected."


# Rögzítem, mikor és milyen modellű oldalfal érkezett a gyártási folyamatba.
def write_part_loaded_log(
    log_dir: str | Path,
    body_id: str,
    config: dict[str, Any],
    timestamp: Any = None,
) -> Path:
    """Record that a new part was received and registered successfully."""
    return _append_line(
        log_dir,
        f"{_local_timestamp(timestamp)} | NEW PART LOADED SUCCESSFULLY | "
        f"Part ID: {body_id} | Model: {_model_name(config)} | "
        f"Weld points expected: {len(config.get('expected_weld_ids', []))}",
    )


# Csak a hibás hegesztési pontról írok részletes sort, így a normál pontok nem árasztják el a szöveges naplót.
def write_weld_error_log(
    log_dir: str | Path,
    event: dict[str, Any],
    errors: list[str],
) -> Path | None:
    """Write an individual weld record only when that weld has a detected error."""
    if not errors:
        return None

    parameters = (
        f"Current: {event.get('current_ka', 'N/A')} kA, "
        f"weld time: {event.get('weld_time_ms', 'N/A')} ms, "
        f"electrode force: {event.get('electrode_force_kn', 'N/A')} kN"
    )
    details = "; ".join(_english_error(error) for error in errors)
    line = (
        f"{_local_timestamp(event.get('timestamp'))} | WELDING FAULT | "
        f"Part ID: {event.get('body_id', 'unknown')} | "
        f"Weld point: {event.get('weld_id', 'unknown')} | "
        f"Fault: {details} | {parameters}"
    )
    return _append_line(log_dir, line)


# A lezárt oldalfalról összesítő bejegyzést készítek a pontteljességgel, hibákkal és ciklusidővel.
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
    """Record one final part-removal outcome after the monitor completes inspection."""
    body = conn.execute(
        "SELECT completed_at,status FROM bodies WHERE body_id=?",
        (body_id,),
    ).fetchone()
    rework = conn.execute(
        "SELECT status FROM rework_queue WHERE body_id=?",
        (body_id,),
    ).fetchone()

    received_expected = len(set(received_ids) & set(expected_ids))
    expected_count = len(set(expected_ids))
    status = str(body["status"] if body else "UNKNOWN")
    timestamp = body["completed_at"] if body else None
    duration = (
        f" | Cycle time: {float(duration_seconds):.1f} s"
        if duration_seconds is not None else ""
    )

    if status == "MEGFELELŐ":
        line = (
            f"{_local_timestamp(timestamp)} | PART REMOVED FROM LINE | "
            f"WELDING COMPLETED SUCCESSFULLY | Part ID: {body_id} | "
            f"Model: {_model_name(config)} | Welded points: "
            f"{received_expected}/{expected_count}{duration}"
        )
        return _append_line(log_dir, line)

    rows = conn.execute(
        "SELECT weld_id,errors_json FROM weld_events WHERE body_id=? ORDER BY id",
        (body_id,),
    ).fetchall()
    error_points: set[str] = set()
    for row in rows:
        try:
            row_errors = json.loads(row["errors_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            row_errors = ["unreadable validation details"]
        if row_errors:
            error_points.add(str(row["weld_id"]))

    # Hosszú azonosítólistát rövidítek, hogy a napló olvasható maradjon.
    def short_ids(values: Any, limit: int = 8) -> str:
        items = [str(value) for value in values or []]
        if not items:
            return "none"
        shown = ", ".join(items[:limit])
        return f"{shown} (+{len(items) - limit} more)" if len(items) > limit else shown

    rework_status = {
        "UTÓMUNKÁRA VÁR": "WAITING FOR REWORK",
        "UTÓMUNKA FOLYAMATBAN": "REWORK IN PROGRESS",
        "UTÓMUNKA ELVÉGEZVE – ÚJRAELLENŐRZÉS SZÜKSÉGES": "REWORK COMPLETED - RE-INSPECTION REQUIRED",
    }.get(str(rework["status"]) if rework else "", "NOT REGISTERED")
    issues = [
        f"Faulty weld points: {len(error_points)}",
        f"Parameter errors: {int(parameter_errors)}",
        f"Missing points: {short_ids(evaluation.get('missing_ids', []))}",
        f"Unexpected points: {short_ids(evaluation.get('unexpected_ids', []))}",
        f"Duplicate points: {short_ids(evaluation.get('duplicate_ids', []))}",
        f"Rework status: {rework_status}",
    ]
    line = (
        f"{_local_timestamp(timestamp)} | PART REMOVED FROM LINE | "
        f"WELDING FAILED | SENT TO REWORK | Part ID: {body_id} | "
        f"Model: {_model_name(config)} | Welded points: "
        f"{received_expected}/{expected_count} | {' | '.join(issues)}{duration}"
    )
    return _append_line(log_dir, line)


# Az utómunka START és COMPLETE állapotváltozását külön naplózom.
def write_rework_action_log(
    log_dir: str | Path,
    body_id: str,
    action: str,
    timestamp: Any = None,
) -> Path:
    """Record rework progress transitions in English."""
    if action == "START":
        message = "REWORK STARTED"
    elif action == "COMPLETE":
        message = "REWORK COMPLETED | READY FOR RE-INSPECTION"
    else:
        message = "REWORK STATUS UPDATED"
    return _append_line(
        log_dir,
        f"{_local_timestamp(timestamp)} | {message} | Part ID: {body_id}",
    )


# A rendszer indulási, leállítási és általános állapotüzeneteit rögzítem.
def write_system_status_log(
    log_dir: str | Path,
    event: str,
    level: str = "ERROR",
    timestamp: Any = None,
) -> Path:
    """Record only warnings/errors; routine UI activity is intentionally omitted."""
    label = event.replace("_", " ").strip().upper() or "SYSTEM EVENT"
    severity = "SYSTEM WARNING" if level.upper() == "WARNING" else "SYSTEM ERROR"
    return _append_line(
        log_dir,
        f"{_local_timestamp(timestamp)} | {severity} | {label}",
    )

# A munkadarab életciklusának rövid eseményeit a production naplóhoz adom.
def write_lifecycle_log(
    log_dir: str | Path,
    event: str,
    timestamp: Any = None,
) -> Path:
    """Write important application lifecycle events immediately to the production log."""
    labels = {
        "application_started": "APPLICATION STARTED",
        "automatic_production_started": "AUTOMATIC PRODUCTION STARTED",
        "automatic_production_stop_requested": "AUTOMATIC PRODUCTION STOP REQUESTED",
        "application_exit_requested": "APPLICATION EXIT REQUESTED",
        "all_services_stopped": "ALL SERVICES STOPPED",
    }
    label = labels.get(str(event), str(event).replace("_", " ").upper())
    return _append_line(
        log_dir,
        f"{_local_timestamp(timestamp)} | SYSTEM STATUS | {label}",
    )

