"""Timestamped Excel exports and complete persisted log snapshots for BODYLINE."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "welding.db"
DEFAULT_LOG_DIR = ROOT / "logs"

TABLE_QUERIES = {
    "bodies": "SELECT * FROM bodies ORDER BY started_at, body_id",
    "weld_events": "SELECT * FROM weld_events ORDER BY id",
    "rework_queue": "SELECT * FROM rework_queue ORDER BY created_at, body_id",
    "rework_actions": "SELECT * FROM rework_actions ORDER BY id",
    "system_errors": "SELECT * FROM system_errors ORDER BY id",
}
EMPTY_COLUMNS = {
    "bodies": ["body_id", "body_type", "config_id", "expected_count", "expected_ids_json", "status",
               "missing_ids_json", "unexpected_ids_json", "duplicate_ids_json", "parameter_errors",
               "event_count", "started_at", "started_received_at", "completed_at", "latency_ms", "duration_seconds"],
    "weld_events": ["id", "body_id", "config_id", "weld_id", "current_ka", "weld_time_ms",
                    "electrode_force_kn", "timestamp", "received_at", "errors_json", "duplicate", "raw_json"],
    "rework_queue": ["body_id", "reason", "status", "created_at", "updated_at", "resolved_at", "resolution_note"],
    "rework_actions": ["id", "body_id", "action", "note", "timestamp"],
    "system_errors": ["id", "category", "detail", "raw_payload", "received_at"],
}


def load_all_tables(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, pd.DataFrame]:
    """Read every available DB row without the dashboard's recent-record display limits."""
    path = Path(db_path)
    tables = {name: pd.DataFrame(columns=EMPTY_COLUMNS[name]) for name in TABLE_QUERIES}
    if not path.exists():
        return tables
    with sqlite3.connect(str(path), timeout=15) as conn:
        conn.execute("PRAGMA busy_timeout=15000")
        existing = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        for name, query in TABLE_QUERIES.items():
            if name in existing:
                tables[name] = pd.read_sql_query(query, conn)
    return tables


def _read_json_records(paths: list[Path], jsonl: bool = False) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(paths):
        try:
            if jsonl:
                with path.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if not line.strip():
                            continue
                        try:
                            row = json.loads(line)
                            records.append(row if isinstance(row, dict) else {
                                "source_file": path.name, "line": line_number, "record": row
                            })
                        except json.JSONDecodeError as exc:
                            records.append({
                                "source_file": path.name, "line": line_number,
                                "parse_error": str(exc), "raw_line": line[:30000],
                            })
            else:
                row = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(row, dict):
                    row.setdefault("source_file", path.name)
                    records.append(row)
        except (OSError, json.JSONDecodeError) as exc:
            records.append({"source_file": path.name, "read_error": str(exc)})
    return records


def load_file_logs(log_dir: str | Path = DEFAULT_LOG_DIR) -> dict[str, pd.DataFrame]:
    """Load per-body, daily, application, console, and aggregate JSON logs."""
    root = Path(log_dir)
    if not root.exists():
        return {
            "run_json": pd.DataFrame(),
            "daily_jsonl": pd.DataFrame(),
            "application_log": pd.DataFrame(),
            "aggregate_json": pd.DataFrame(),
            "console_log": pd.DataFrame(),
        }
    summary_path = root / "production_summary.json"
    aggregate_records = _read_json_records([summary_path]) if summary_path.exists() else []
    console_records: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    console_records.append({
                        "source_file": path.name,
                        "line": line_number,
                        "timestamp": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                        "message": line.rstrip("\r\n")[:30000],
                    })
        except OSError as exc:
            console_records.append({"source_file": path.name, "read_error": str(exc)})
    return {
        "run_json": pd.DataFrame(_read_json_records(list(root.glob("run_*.json")))),
        "daily_jsonl": pd.DataFrame(_read_json_records(list(root.glob("production_*.jsonl")), jsonl=True)),
        "application_log": pd.DataFrame(_read_json_records(list(root.glob("application_*.jsonl")), jsonl=True)),
        "aggregate_json": pd.DataFrame(aggregate_records),
        "console_log": pd.DataFrame(console_records),
    }


def append_application_log(
    event: str,
    details: dict[str, Any] | None = None,
    log_dir: str | Path = DEFAULT_LOG_DIR,
    level: str = "INFO",
) -> Path:
    """Append and flush an operator/app action immediately so it survives a shutdown."""
    root = Path(log_dir)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    path = root / f"application_{now.strftime('%Y-%m-%d')}.jsonl"
    row = {"timestamp": now.isoformat(), "level": level, "event": event, "details": details or {}}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _session_filter(bodies: pd.DataFrame, session_started_at: float | None) -> pd.DataFrame:
    if bodies.empty or "started_at" not in bodies.columns or session_started_at is None:
        return bodies.copy()
    started = pd.to_datetime(bodies["started_at"], utc=True, errors="coerce")
    cutoff = pd.to_datetime(float(session_started_at), unit="s", utc=True)
    return bodies.loc[started >= cutoff - pd.Timedelta(seconds=2)].copy()


def _percent(numerator: int | float, denominator: int | float) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def _make_summary(
    tables: dict[str, pd.DataFrame],
    session_started_at: float | None,
    fault_rate_percent: float,
    fault_mode: str,
    automatic_worker_stopped: bool,
    export_timestamp: str,
    speed_percent: float = 100.0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    bodies_all = tables["bodies"]
    bodies_session = _session_filter(bodies_all, session_started_at)
    completed = bodies_session.loc[bodies_session["status"].ne("FOLYAMATBAN")] if not bodies_session.empty else bodies_session
    good = int(completed["status"].eq("MEGFELELŐ").sum()) if not completed.empty else 0
    scrap = int(completed["status"].astype(str).str.contains("SELEJT", na=False).sum()) if not completed.empty else 0
    in_progress = int(bodies_session["status"].eq("FOLYAMATBAN").sum()) if not bodies_session.empty else 0
    durations = pd.to_numeric(completed.get("duration_seconds", pd.Series(dtype=float)), errors="coerce").dropna()
    under_20 = int((durations < 20.0).sum())
    params = pd.to_numeric(completed.get("parameter_errors", pd.Series(dtype=float)), errors="coerce").fillna(0)
    events = tables["weld_events"]
    session_ids = set(bodies_session.get("body_id", pd.Series(dtype=str)).astype(str))
    session_events = events[events["body_id"].astype(str).isin(session_ids)] if not events.empty and "body_id" in events else events.iloc[0:0]
    rework = tables["rework_queue"]
    session_rework = rework[rework["body_id"].astype(str).isin(session_ids)] if not rework.empty else rework
    errors = tables["system_errors"]
    actions = tables["rework_actions"]
    session_actions = actions[actions["body_id"].astype(str).isin(session_ids)] if not actions.empty else actions

    metrics = [
        {"Kategória": "Jelentés", "Mutató": "Export létrehozva", "Érték": export_timestamp, "Megjegyzés": "Helyi gép dátuma és ideje"},
        {"Kategória": "Jelentés", "Mutató": "Munkamenet kezdete (Unix idő)", "Érték": session_started_at, "Megjegyzés": "A dashboard-munkamenet kezdete"},
        {"Kategória": "Jelentés", "Mutató": "Automatika leállt az exportig", "Érték": automatic_worker_stopped, "Megjegyzés": "False esetén az Excel az automatikus leállásra várás nélkül is elkészült"},
        {"Kategória": "Beállítások", "Mutató": "Pont-eltérés valószínűsége (%)", "Érték": round(float(fault_rate_percent), 3), "Megjegyzés": "Egy hegesztési pontra vonatkozó esély"},
        {"Kategória": "Beállítások", "Mutató": "Eltérés módja", "Érték": fault_mode, "Megjegyzés": "within_limits = határon belül; outside_limits = határon kívül"},
        {"Kategória": "Beállítások", "Mutató": "Szimulációs sebesség (%)", "Érték": float(speed_percent), "Megjegyzés": "100% = eredeti beállítás; a küldési késleltetés és a karosszériák közötti szünet skálázott"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Oldalfalak összesen", "Érték": len(bodies_session), "Megjegyzés": "A munkamenetben indított karosszériák"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Lezárt oldalfalak", "Érték": len(completed), "Megjegyzés": "Nem FOLYAMATBAN állapotú karosszériák"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Folyamatban exportkor", "Érték": in_progress, "Megjegyzés": "Ezek a rekordok is szerepelnek a részletes adatok között"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Megfelelt darab (db)", "Érték": good, "Megjegyzés": "MEGFELELŐ állapot"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Selejtes / utómunkás darab (db)", "Érték": scrap, "Megjegyzés": "SELEJT státuszú karosszériák"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Megfelelési arány (%)", "Érték": _percent(good, len(completed)), "Megjegyzés": "Megfelelt / lezárt oldalfalak"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Selejtarány (%)", "Érték": _percent(scrap, len(completed)), "Megjegyzés": "Selejtes / lezárt oldalfalak"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Átlagos ciklusidő (mp)", "Érték": round(float(durations.mean()), 3) if not durations.empty else None, "Megjegyzés": "Lezárt ciklusok alapján"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "20 mp alatti ciklusok (db)", "Érték": under_20, "Megjegyzés": f"A mért idővel rendelkező lezárt ciklusokból: {len(durations)} db"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Paraméterhibák összesen", "Érték": int(params.sum()) if not params.empty else 0, "Megjegyzés": "A lezárt munkamenetbeli karosszériák alapján"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Hegesztési események (db)", "Érték": len(session_events), "Megjegyzés": "Minden mentett pontüzenet, duplikáltakkal együtt"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Utómunka-bejegyzések (db)", "Érték": len(session_rework), "Megjegyzés": "A munkamenetben indult karosszériákhoz"},
        {"Kategória": "Aktuális munkamenet", "Mutató": "Utómunka-műveletek (db)", "Érték": len(session_actions), "Megjegyzés": "START/COMPLETE operátori műveletek"},
        {"Kategória": "Teljes adatbázis", "Mutató": "Oldalfalak összesen", "Érték": len(bodies_all), "Megjegyzés": "Minden megőrzött munkamenet és történeti rekord"},
        {"Kategória": "Teljes adatbázis", "Mutató": "Hegesztési események összesen", "Érték": len(events), "Megjegyzés": "Minden elmentett hegesztési pont-esemény"},
        {"Kategória": "Teljes adatbázis", "Mutató": "Rendszerhibák összesen", "Érték": len(errors), "Megjegyzés": "A monitor SQLite-hibanaplója"},
        {"Kategória": "Teljes adatbázis", "Mutató": "Utómunka-műveletek összesen", "Érték": len(actions), "Megjegyzés": "A teljes adatbázisban rögzített műveletek"},
    ]
    summary = pd.DataFrame(metrics)

    model_rows = []
    if not bodies_session.empty:
        for config_id, group in bodies_session.groupby("config_id", dropna=False):
            done = group.loc[group["status"].astype(str).ne("FOLYAMATBAN")]
            model_good = int(done["status"].eq("MEGFELELŐ").sum())
            model_scrap = int(done["status"].astype(str).str.contains("SELEJT", na=False).sum())
            group_durations = pd.to_numeric(done.get("duration_seconds", pd.Series(dtype=float)), errors="coerce").dropna()
            model_rows.append({
                "Modellazonosító": config_id,
                "Gyártó / modell": str(group.iloc[0].get("body_type", "")),
                "Összes oldalfal": len(group),
                "Lezárt": len(done),
                "Megfelelt (db)": model_good,
                "Selejtes (db)": model_scrap,
                "Megfelelési arány (%)": _percent(model_good, len(done)),
                "Selejtarány (%)": _percent(model_scrap, len(done)),
                "Átlagos ciklusidő (mp)": round(float(group_durations.mean()), 3) if not group_durations.empty else None,
                "Paraméterhibák": int(pd.to_numeric(done.get("parameter_errors", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
            })
    by_model = pd.DataFrame(model_rows, columns=[
        "Modellazonosító", "Gyártó / modell", "Összes oldalfal", "Lezárt", "Megfelelt (db)",
        "Selejtes (db)", "Megfelelési arány (%)", "Selejtarány (%)", "Átlagos ciklusidő (mp)", "Paraméterhibák",
    ])
    info = {
        "export_timestamp": export_timestamp, "session_body_count": len(bodies_session),
        "session_completed_count": len(completed), "session_pass_count": good,
        "session_scrap_count": scrap, "session_in_progress_count": in_progress,
        "session_pass_rate_percent": _percent(good, len(completed)),
        "session_scrap_rate_percent": _percent(scrap, len(completed)),
        "speed_percent": float(speed_percent),
        "total_weld_events": len(events), "total_system_errors": len(errors), "total_bodies": len(bodies_all),
    }
    return summary, by_model, info


def _make_wear_summary_frame(events: pd.DataFrame) -> pd.DataFrame:
    """Aggregate electrode-wear and correction details persisted in raw MQTT events."""
    columns = [
        "Modellazonosító", "Hegesztési pontok", "Sikeres önkorrekciók",
        "Korrekciós lépések", "Sikertelen korrekciók",
        "Legnagyobb kopás (%)", "Átlagos minőségi mutató (%)",
    ]
    if events.empty or "raw_json" not in events.columns:
        return pd.DataFrame([{"Megjegyzés": "Még nincs rögzített elektródakopási adat."}])

    grouped: dict[str, dict[str, Any]] = {}
    all_values: list[dict[str, Any]] = []
    for raw in events["raw_json"].tolist():
        try:
            payload = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("event_type") != "weld_result" or payload.get("electrode_wear_enabled") is not True:
            continue
        model = str(payload.get("config_id") or "Ismeretlen")
        for key in (model, "ÖSSZESEN"):
            bucket = grouped.setdefault(key, {
                "points": 0, "corrected": 0, "steps": 0, "failed": 0,
                "max_wear": 0.0, "quality_sum": 0.0, "quality_count": 0,
            })
            bucket["points"] += 1
            bucket["corrected"] += int(bool(payload.get("auto_correction_applied")))
            bucket["steps"] += int(payload.get("auto_correction_steps", 0) or 0)
            bucket["failed"] += int(payload.get("process_quality_ok") is False)
            bucket["max_wear"] = max(bucket["max_wear"], float(payload.get("electrode_wear_percent", 0.0) or 0.0))
            quality = payload.get("simulated_quality_index_percent")
            if isinstance(quality, (int, float)):
                bucket["quality_sum"] += float(quality)
                bucket["quality_count"] += 1

    rows = []
    for model, values in grouped.items():
        rows.append({
            "Modellazonosító": model,
            "Hegesztési pontok": values["points"],
            "Sikeres önkorrekciók": values["corrected"],
            "Korrekciós lépések": values["steps"],
            "Sikertelen korrekciók": values["failed"],
            "Legnagyobb kopás (%)": round(values["max_wear"], 3),
            "Átlagos minőségi mutató (%)": (
                round(values["quality_sum"] / values["quality_count"], 2)
                if values["quality_count"] else None
            ),
        })
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(
        [{"Megjegyzés": "A naplózott események között nincs bekapcsolt kopásmodellből származó adat."}
    ])


def _excel_safe(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert structured Python values to text before passing them to openpyxl."""
    result = frame.copy()
    for column in result.columns:
        result[column] = result[column].map(
            lambda value: json.dumps(value, ensure_ascii=False, default=str)
            if isinstance(value, (dict, list, tuple)) else
            (str(value)[:32000] if isinstance(value, str) and len(value) > 32000 else value)
        )
    return result


EXCEL_MAX_ROWS = 1_048_576
EXCEL_MAX_DATA_ROWS = EXCEL_MAX_ROWS - 1  # reserve row 1 for column headings


def split_long_sheets(
    sheets: dict[str, pd.DataFrame],
    max_data_rows: int = EXCEL_MAX_DATA_ROWS,
) -> dict[str, pd.DataFrame]:
    """Split dataframes into Excel-safe worksheets without dropping any rows."""
    if max_data_rows < 1 or max_data_rows >= EXCEL_MAX_ROWS:
        raise ValueError(f"max_data_rows must be from 1 to {EXCEL_MAX_DATA_ROWS}")
    expanded: dict[str, pd.DataFrame] = {}
    for sheet_name, frame in sheets.items():
        if len(frame) <= max_data_rows:
            expanded[sheet_name] = frame
            continue
        for part_index, start in enumerate(range(0, len(frame), max_data_rows), start=1):
            suffix = f" {part_index}"
            safe_name = f"{sheet_name[:31 - len(suffix)]}{suffix}"
            expanded[safe_name] = frame.iloc[start:start + max_data_rows].copy()
    return expanded


def export_production_report(
    session_started_at: float | None,
    fault_rate_percent: float,
    fault_mode: str,
    automatic_worker_stopped: bool,
    db_path: str | Path = DEFAULT_DB_PATH,
    log_dir: str | Path = DEFAULT_LOG_DIR,
    export_timestamp: datetime | None = None,
    speed_percent: float = 100.0,
    wear_enabled: bool = True,
    wear_per_point_percent: float = 0.03,
    auto_correct_wear: bool = True,
) -> tuple[Path, bytes, dict[str, Any]]:
    """Write a dated Excel report to disk and return its bytes for browser download."""
    now = export_timestamp or datetime.now().astimezone()
    # Include microseconds so two exports in the same second never overwrite one another.
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S_%f")
    root = Path(log_dir)
    export_dir = root / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    target = export_dir / f"BODYLINE_jelentes_{stamp}.xlsx"

    tables = load_all_tables(db_path)
    file_logs = load_file_logs(root)
    summary, by_model, info = _make_summary(
        tables, session_started_at, fault_rate_percent, fault_mode,
        automatic_worker_stopped, now.isoformat(timespec="seconds"),
        speed_percent=speed_percent,
    )
    settings = pd.DataFrame([
        {"Beállítás": "Jelentés fájlneve", "Érték": target.name},
        {"Beállítás": "Adatbázis elérési útja", "Érték": str(Path(db_path).resolve())},
        {"Beállítás": "Napló mappája", "Érték": str(root.resolve())},
        {"Beállítás": "Pont-eltérés valószínűsége (%)", "Érték": float(fault_rate_percent)},
        {"Beállítás": "Eltérés módja", "Érték": fault_mode},
        {"Beállítás": "Szimulációs sebesség (%)", "Érték": float(speed_percent)},
        {"Beállítás": "Elektródakopás modellezése", "Érték": bool(wear_enabled)},
        {"Beállítás": "Kopás hegesztési pontonként (%)", "Érték": float(wear_per_point_percent)},
        {"Beállítás": "Automatikus önkorrekció", "Érték": bool(auto_correct_wear)},
        {"Beállítás": "Minőségi célérték (%)", "Érték": 95.0},
        {"Beállítás": "Automatika leállt az exportig", "Érték": bool(automatic_worker_stopped)},
        {"Beállítás": "Megjegyzés", "Érték": "A részletes lapok minden elérhető adatbázisrekordot tartalmaznak, nem csak a képernyőn látható legutóbbi sorokat."},
    ])
    sheets = {
        "Összesítő": summary,
        "Modellenként": by_model,
        "Karosszériák": tables["bodies"],
        "Hegesztési adatok": tables["weld_events"],
        "Kopás és önkorrekció": _make_wear_summary_frame(tables["weld_events"]),
        "Utómunka sor": tables["rework_queue"],
        "Utómunka műveletek": tables["rework_actions"],
        "Rendszerhibák": tables["system_errors"],
        "Futásnaplók": file_logs["run_json"],
        "Napi JSONL": file_logs["daily_jsonl"],
        "Összesített JSON": file_logs["aggregate_json"],
        "Alkalmazás-napló": file_logs["application_log"],
        "Konzolnapló": file_logs["console_log"],
        "Beállítások": settings,
    }

    temp = target.with_suffix(".tmp.xlsx")
    safe_sheets = split_long_sheets(sheets)
    with pd.ExcelWriter(temp, engine="openpyxl") as writer:
        for sheet_name, frame in safe_sheets.items():
            safe_frame = _excel_safe(frame)
            if safe_frame.empty and len(safe_frame.columns) == 0:
                safe_frame = pd.DataFrame({"Információ": ["Nincs rögzített adat."]})
            safe_frame.to_excel(writer, index=False, sheet_name=sheet_name)
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            worksheet.sheet_view.showGridLines = False
            for cell in worksheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="2457D6")
                cell.alignment = Alignment(vertical="center", wrap_text=True)
            worksheet.row_dimensions[1].height = 30
            # Only scan a small prefix to estimate widths. Iterating all cells here
            # would be expensive for long-running high-speed simulations with huge logs.
            sample_rows = min(250, worksheet.max_row)
            for column_index in range(1, worksheet.max_column + 1):
                max_len = 10
                for row_index in range(1, sample_rows + 1):
                    value = worksheet.cell(row=row_index, column=column_index).value
                    text_value = "" if value is None else str(value)
                    max_len = max(max_len, min(len(text_value), 52))
                    if row_index > 1:
                        worksheet.cell(row=row_index, column=column_index).alignment = Alignment(vertical="top", wrap_text=False)
                worksheet.column_dimensions[get_column_letter(column_index)].width = min(max_len + 2, 48)
    os.replace(temp, target)
    return target, target.read_bytes(), info
