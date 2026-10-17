"""Modern, compact two-tab Streamlit dashboard for automatic sidewall welding simulation."""
from __future__ import annotations

import html
import importlib
import json
import os
import random
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any

import pandas as pd
import paho.mqtt.client as mqtt
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.catalog import CatalogError, get_configuration, list_configurations
from src.monitor import (
    BROKER_HOST, BROKER_PORT, DB_PATH, REWORK_DONE,
    REWORK_IN_PROGRESS, REWORK_WAITING, TOPIC,
)
from src import simulator as simulator_module
from src.report_export import append_application_log, export_production_report, load_all_tables, load_file_logs

BETWEEN_BODIES_PAUSE_SECONDS = 10.0
PUBLISH_DELAY_MS = 90  # milliseconds per weld result; 142 points take about 13 seconds
DEFAULT_FAULT_RATE = 0.0

st.set_page_config(
    page_title="BODYLINE | Ipar 4.0",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
      :root { --ink:#15253c; --muted:#6c7a90; --line:#e3eaf2; --panel:#ffffff; --blue:#2457d6; --teal:#13a887; }
      html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
      .stApp { background:linear-gradient(145deg,#f5f8fc 0%,#eef3f9 100%); color:var(--ink); }
      [data-testid="stAppViewContainer"] .main .block-container { max-width:1560px; padding:1rem 1.5rem 1rem; }
      header[data-testid="stHeader"] { background:transparent; height:2rem; }
      [data-testid="stToolbar"], #MainMenu, footer { visibility:hidden; }
      h1,h2,h3 { font-family:'Space Grotesk',sans-serif !important; color:var(--ink); letter-spacing:-.03em; }
      h1 { font-size:1.85rem !important; margin:0 0 .15rem 0 !important; }
      h2 { font-size:1.15rem !important; margin:.2rem 0 .45rem !important; }
      h3 { font-size:1rem !important; }
      p, label, .stCaption { color:var(--muted); }
      div[data-testid="stTabs"] button { font-weight:700; font-size:.94rem; padding:.7rem 1.1rem; }
      div[data-testid="stTabs"] button[aria-selected="true"] { color:var(--blue); }
      div[data-testid="stMetric"] { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:.7rem .9rem; box-shadow:0 4px 16px #233c5b08; }
      div[data-testid="stMetricLabel"] { font-size:.75rem; }
      div[data-testid="stMetricValue"] { font-family:'Space Grotesk',sans-serif; font-size:1.48rem; }
      div[data-testid="stProgress"] > div { border-radius:999px; height:.6rem; }
      .hero { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:1.05rem 1.2rem; margin:.15rem 0 .8rem; background:#fff; border:1px solid var(--line); border-radius:18px; box-shadow:0 8px 24px #233c5b0a; }
      .hero-title { color:var(--ink); font:700 1.2rem 'Space Grotesk',sans-serif; letter-spacing:-.025em; }
      .hero-sub { color:var(--muted); font-size:.82rem; margin-top:.25rem; }
      .pill { white-space:nowrap; display:inline-flex; align-items:center; gap:.45rem; border-radius:999px; padding:.4rem .75rem; font-size:.76rem; font-weight:700; }
      .pill-live { color:#08785f; background:#e3f8f1; }
      .pill-off { color:#66758b; background:#edf1f6; }
      .dot { width:7px; height:7px; border-radius:50%; display:inline-block; background:currentColor; }
      .section-label { margin:.5rem 0 .45rem; color:#61718a; font-size:.75rem; font-weight:700; text-transform:uppercase; letter-spacing:.09em; }
      .reading { display:flex; justify-content:space-between; gap:.7rem; align-items:center; border:1px solid var(--line); background:#fff; border-radius:12px; padding:.62rem .8rem; min-height:58px; }
      .reading-label { font-size:.7rem; color:var(--muted); }
      .reading-value { margin-top:.15rem; font:700 1.05rem 'Space Grotesk',sans-serif; color:var(--ink); }
      .spot-grid { display:grid; grid-template-columns:repeat(16,minmax(0,1fr)); gap:4px; padding:.6rem; border:1px solid var(--line); border-radius:14px; background:#fff; }
      .spot { display:flex; align-items:center; justify-content:center; height:22px; min-width:0; border-radius:5px; font-size:.65rem; font-weight:700; letter-spacing:-.02em; }
      .spot-ok { color:#08785f; background:#dff7ed; }
      .spot-wait { color:#7a899e; background:#edf1f6; }
      .spot-bad { color:#b42336; background:#ffe5e8; }
      .spot-warn { color:#8a5a00; background:#fff1ce; }
      .legend { display:flex; flex-wrap:wrap; gap:.9rem; margin:.35rem 0 .65rem; color:var(--muted); font-size:.72rem; }
      .legend span { display:flex; align-items:center; gap:.35rem; }
      .legend i { width:8px; height:8px; border-radius:3px; display:inline-block; }
      .compact-note { color:var(--muted); font-size:.74rem; }
      div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
      div.stButton > button { border-radius:10px; font-weight:700; }
      div.stButton > button[kind="primary"] { background:var(--blue); border-color:var(--blue); }
      @media(max-width:900px) { .spot-grid { grid-template-columns:repeat(10,minmax(0,1fr)); } .hero { align-items:flex-start; flex-direction:column; } }
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    CATALOG = list_configurations()
except CatalogError as exc:
    st.error(f"Nem olvasható az Excel-katalógus: {exc}")
    st.stop()

CONFIG_BY_ID = {cfg["config_id"]: cfg for cfg in CATALOG}


def publish_control_event(event: dict[str, Any]) -> None:
    """Send operator actions through MQTT so the monitor controls state transitions."""
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"welding-ui-{int(time.time() * 1000) % 100000000}",
    )
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=15)
    client.loop_start()
    try:
        info = client.publish(TOPIC, json.dumps(event, ensure_ascii=False), qos=1)
        info.wait_for_publish(timeout=5)
        if info.rc != mqtt.MQTT_ERR_SUCCESS or not info.is_published():
            raise RuntimeError(f"Az MQTT-műveletet nem igazolta vissza a broker (rc={info.rc}).")
    finally:
        client.loop_stop()
        client.disconnect()


def read_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not DB_PATH.exists():
        return tuple(pd.DataFrame() for _ in range(5))  # type: ignore[return-value]
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        bodies = pd.read_sql_query("SELECT * FROM bodies ORDER BY started_at DESC", conn)
        events = pd.read_sql_query("SELECT * FROM weld_events ORDER BY id DESC LIMIT 1800", conn)
        rework = pd.read_sql_query("SELECT * FROM rework_queue ORDER BY created_at DESC", conn)
        errors = pd.read_sql_query("SELECT * FROM system_errors ORDER BY id DESC LIMIT 100", conn)
        actions = pd.read_sql_query("SELECT * FROM rework_actions ORDER BY id DESC LIMIT 100", conn)
    return bodies, events, rework, errors, actions


def json_list(value: Any) -> list[str]:
    try:
        result = json.loads(value or "[]")
        return [str(item) for item in result] if isinstance(result, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def automatic_production_worker(
    stop_event: threading.Event, state: dict[str, Any], config_ids: list[str]
) -> None:
    """Publish a randomly selected sidewall, then wait 10 seconds between bodies."""
    state["running"] = True
    previous_config = ""
    while not stop_event.is_set():
        options = [value for value in config_ids if value != previous_config] or config_ids
        config_id = random.choice(options)
        previous_config = config_id
        try:
            # Streamlit reruns the dashboard but may keep imported modules cached.
            # Reload the simulator module so changes pulled from Git are picked up here too.
            importlib.reload(simulator_module)
            body_id, events = simulator_module.generate_body_events(
                config_id,
                fault_rate=float(state.get("fault_rate", DEFAULT_FAULT_RATE)),
                fault_mode=str(state.get("fault_mode", "within_limits")),
            )
            state["body_id"] = body_id
            state["config_id"] = config_id
            state["last_started_at"] = pd.Timestamp.now().strftime("%H:%M:%S")
            state["error"] = None
            simulator_module.publish_events(events, delay_ms=PUBLISH_DELAY_MS)
            state["completed_cycles"] = int(state.get("completed_cycles", 0)) + 1
            state["last_sent_body_id"] = body_id
        except Exception as exc:
            detail = str(exc)
            if "unexpected keyword argument 'fault_mode'" in detail:
                detail = (
                    "A szimulátor régi Python-modulja van betöltve. A rendszer megpróbálja "
                    "újratölteni a src/simulator.py fájlt a következő ciklus előtt. "
                    f"Részlet: {detail}"
                )
            state["error"] = detail
        # A full cycle must finish before the separate 10-second inter-body pause begins.
        stop_event.wait(BETWEEN_BODIES_PAUSE_SECONDS)
    state["running"] = False


def session_bodies_only(bodies: pd.DataFrame) -> pd.DataFrame:
    """Keep KPIs scoped to this browser session so old failed runs do not skew the new rate."""
    if bodies.empty or "started_at" not in bodies:
        return bodies.copy()
    started_at = pd.to_datetime(bodies["started_at"], utc=True, errors="coerce")
    session_start = pd.to_datetime(
        st.session_state.get("app_session_started_at", time.time()), unit="s", utc=True
    )
    return bodies.loc[started_at >= session_start - pd.Timedelta(seconds=2)].copy()


def render_fault_controls() -> None:
    """Let the operator configure injected faults before starting production."""
    st.markdown("### Pontonkénti eltérés beállítása")
    rate_col, mode_col = st.columns([1, 1])
    with rate_col:
        fault_rate_percent = st.slider(
            "Egy hegesztési pont eltérésének esélye (%)",
            min_value=0.0,
            max_value=0.1,
            value=0.0,
            step=0.001,
            format="%.3f%%",
            key="fault_rate_percent_v3",
            help="0,000% esetén nincs mesterséges eltérés. A beállítás minden hegesztési pontra külön érvényes.",
        )
    with mode_col:
        fault_mode_label = st.selectbox(
            "Az eltérés viselkedése",
            options=[
                "Megengedett tartományon belül marad (megfelelő)",
                "Átlépi a határértéket (utómunka)",
            ],
            index=0,
            key="fault_mode_choice_v3",
            help=(
                "Az első mód a mérési értéket a megengedett határon belül tartja. "
                "A második mód a kiválasztott ponton szándékosan határértéken kívüli értéket hoz létre."
            ),
        )
    st.session_state["selected_fault_rate"] = float(fault_rate_percent) / 100.0
    st.session_state["selected_fault_mode"] = (
        "outside_limits" if fault_mode_label.startswith("Átlépi") else "within_limits"
    )
    st.session_state["auto_state"]["fault_rate"] = st.session_state["selected_fault_rate"]
    st.session_state["auto_state"]["fault_mode"] = st.session_state["selected_fault_mode"]
    mode_description = (
        "a kijelölt eltérés határértéken kívülre kerül (utómunka várható)"
        if st.session_state["auto_state"]["fault_mode"] == "outside_limits"
        else "a kijelölt eltérés a határértéken belül marad (megfelelő)"
    )
    st.caption(f"Beállítva: {fault_rate_percent:.3f}% pontonként · {mode_description}. Az értékek indításig módosíthatók.")


def start_automatic_production() -> None:
    """Start production only after the operator presses the start button."""
    old_thread = st.session_state.get("auto_thread")
    old_stop = st.session_state.get("auto_stop_event")
    if old_thread is not None and old_thread.is_alive():
        if old_stop is None or not old_stop.is_set():
            return
        # A stop request cannot interrupt a sidewall that is already being published.
        # Wait for that cycle to finish so a second worker cannot duplicate production.
        old_thread.join(timeout=30.0)
        if old_thread.is_alive():
            state = st.session_state.get("auto_state", {})
            state["error"] = "A korábbi gyártási ciklus még fut; várd meg a befejezését, majd indítsd újra."
            return

    state = st.session_state.get("auto_state")
    if state is None:
        state = {
            "running": False, "completed_cycles": 0, "fault_rate": DEFAULT_FAULT_RATE,
            "fault_mode": "within_limits",
            "session_started_at": st.session_state.get("app_session_started_at", time.time()),
            "body_id": "", "config_id": "", "last_started_at": "", "last_sent_body_id": "",
            "error": None,
        }
    # Preserve the operator's choices made on the statistics tab; starting must not
    # reset the probability or selected variation mode back to the defaults.
    state["running"] = True
    state["fault_rate"] = float(state.get("fault_rate", DEFAULT_FAULT_RATE))
    state["fault_mode"] = str(state.get("fault_mode", "within_limits"))
    state.setdefault("completed_cycles", 0)
    state.setdefault("session_started_at", st.session_state.get("app_session_started_at", time.time()))
    state.setdefault("body_id", "")
    state.setdefault("config_id", "")
    state.setdefault("last_started_at", "")
    state.setdefault("last_sent_body_id", "")
    state["error"] = None

    stop_event = threading.Event()
    worker = threading.Thread(
        target=automatic_production_worker, args=(stop_event, state, list(CONFIG_BY_ID)),
        name="automatic-welding-production", daemon=True,
    )
    st.session_state["auto_stop_event"] = stop_event
    st.session_state["auto_state"] = state
    st.session_state["auto_thread"] = worker
    worker.start()
    safe_application_log("automatic_production_started", {
        "fault_rate_percent": round(float(state["fault_rate"]) * 100.0, 3),
        "fault_mode": state["fault_mode"],
    })


def safe_application_log(event: str, details: dict[str, Any] | None = None, level: str = "INFO") -> None:
    """Best-effort disk-backed app log; a logging issue must not block export."""
    try:
        append_application_log(event, details, log_dir=ROOT / "logs", level=level)
    except Exception as exc:
        print(f"Alkalmazásnapló nem írható ({event}): {exc}")


def make_excel_export(stop_automatic: bool = False) -> dict[str, Any]:
    """Persist an Excel snapshot first, independent of whether the production worker stops."""
    state = st.session_state.get("auto_state", {})
    stop_event = st.session_state.get("auto_stop_event")
    worker = st.session_state.get("auto_thread")
    fault_rate_percent = float(state.get("fault_rate", DEFAULT_FAULT_RATE)) * 100.0
    fault_mode = str(state.get("fault_mode", "within_limits"))
    session_started_at = st.session_state.get("app_session_started_at")
    export_time = datetime.now().astimezone().replace(microsecond=0)

    if stop_automatic:
        safe_application_log("logout_requested", {
            "fault_rate_percent": fault_rate_percent,
            "fault_mode": fault_mode,
            "worker_was_alive": bool(worker is not None and worker.is_alive()),
        })
        if stop_event is not None:
            stop_event.set()
        state["running"] = False

    # Write the first dated workbook immediately. This is not conditional on the
    # automation thread shutting down, so even a stuck worker cannot block the export.
    worker_stopped = worker is None or not worker.is_alive()
    path, data, summary = export_production_report(
        session_started_at=session_started_at,
        fault_rate_percent=fault_rate_percent,
        fault_mode=fault_mode,
        automatic_worker_stopped=worker_stopped,
        db_path=DB_PATH,
        log_dir=ROOT / "logs",
        export_timestamp=export_time,
    )
    safe_application_log("excel_report_created", {
        "file": str(path),
        "snapshot": "Első mentés; nem vár az automatikus leállásra.",
        "session_body_count": summary.get("session_body_count", 0),
        "session_completed_count": summary.get("session_completed_count", 0),
        "session_scrap_count": summary.get("session_scrap_count", 0),
    })

    if stop_automatic and worker is not None and worker.is_alive():
        # Normal cycles finish in about 13 seconds. Timeout does not cancel the export.
        worker.join(timeout=20.0)
    worker_stopped = worker is None or not worker.is_alive()
    safe_application_log(
        "logout_export_finalized" if stop_automatic else "excel_export_prepared",
        {
            "file": str(path),
            "automatic_worker_stopped": worker_stopped,
            "export_remains_valid_if_worker_continues": True,
        },
    )

    # Refresh the same timestamped workbook with rows written while the worker stopped.
    # If this second pass fails, the first successfully written workbook stays available.
    try:
        final_path, final_data, final_summary = export_production_report(
            session_started_at=session_started_at,
            fault_rate_percent=fault_rate_percent,
            fault_mode=fault_mode,
            automatic_worker_stopped=worker_stopped,
            db_path=DB_PATH,
            log_dir=ROOT / "logs",
            export_timestamp=export_time,
        )
        path, data, summary = final_path, final_data, final_summary
    except Exception as exc:
        safe_application_log("excel_report_refresh_failed", {
            "file": str(path), "error": str(exc),
            "note": "The first successfully written Excel snapshot is retained.",
        }, level="WARNING")

    safe_application_log("excel_report_ready", {
        "file": str(path),
        "automatic_worker_stopped": worker_stopped,
        "all_database_rows_included": True,
    })
    return {
        "path": str(path),
        "filename": path.name,
        "data": data,
        "summary": summary,
        "automatic_worker_stopped": worker_stopped,
        "created_at": export_time.isoformat(timespec="seconds"),
    }


def render_complete_log_tab() -> None:
    """Display every persisted record and every log file, not only recent dashboard rows."""
    st.markdown("## Teljes napló és export")
    st.caption(
        "A hegesztési események, karosszériák, utómunka-műveletek és rendszerhibák SQLite-adatbázisba "
        "kerülnek. A futás- és alkalmazásnaplók fájlba íródnak, így egy váratlan bezárás után is megmaradnak."
    )
    if st.button("⬇  Teljes Excel-jelentés készítése", key="manual_excel_export", type="primary"):
        try:
            report = make_excel_export(stop_automatic=False)
            st.session_state["latest_report"] = report
            safe_application_log("excel_export_download_available", {"file": report["path"]})
            st.success(f"Az Excel-jelentés elmentve: {report['filename']}")
        except Exception as exc:
            st.error(f"Az Excel-jelentés nem készült el: {exc}")

    latest_report = st.session_state.get("latest_report")
    if latest_report:
        st.download_button(
            "Excel-jelentés letöltése",
            data=latest_report["data"],
            file_name=latest_report["filename"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_latest_excel_report",
            use_container_width=True,
        )
        summary = latest_report.get("summary", {})
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Munkamenet oldalfalai", int(summary.get("session_body_count", 0)))
        s2.metric("Lezárt oldalfalak", int(summary.get("session_completed_count", 0)))
        s3.metric("Megfelelt", int(summary.get("session_pass_count", 0)))
        s4.metric("Selejtes", int(summary.get("session_scrap_count", 0)))

    try:
        tables = load_all_tables(DB_PATH)
        file_logs = load_file_logs(ROOT / "logs")
    except Exception as exc:
        st.error(f"A naplók beolvasása közben hiba történt: {exc}")
        return

    bodies, weld_events = tables["bodies"], tables["weld_events"]
    rework, actions, errors = tables["rework_queue"], tables["rework_actions"], tables["system_errors"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mentett karosszéria", len(bodies))
    c2.metric("Mentett hegesztési esemény", len(weld_events))
    c3.metric("Utómunka-művelet", len(actions))
    c4.metric("Rendszerhiba-bejegyzés", len(errors))
    st.caption(f"Adatbázis: {DB_PATH} · Excel-exportok: {ROOT / 'logs' / 'exports'}")

    with st.expander(f"Karosszéria-rekordok ({len(bodies)})", expanded=False):
        st.dataframe(bodies, use_container_width=True, hide_index=True, height=320)
    with st.expander(f"Összes hegesztési pont-esemény ({len(weld_events)})", expanded=False):
        st.dataframe(weld_events, use_container_width=True, hide_index=True, height=360)
    with st.expander(f"Összes utómunka-bejegyzés ({len(rework)})", expanded=False):
        st.dataframe(rework, use_container_width=True, hide_index=True, height=280)
    with st.expander(f"Összes utómunka-művelet ({len(actions)})", expanded=False):
        st.dataframe(actions, use_container_width=True, hide_index=True, height=280)
    with st.expander(f"Összes rendszerhiba ({len(errors)})", expanded=False):
        st.dataframe(errors, use_container_width=True, hide_index=True, height=280)
    with st.expander(f"Karosszériánkénti JSON-naplók ({len(file_logs['run_json'])})", expanded=False):
        if file_logs["run_json"].empty:
            st.info("Még nincs per-karosszéria JSON-napló.")
        else:
            st.dataframe(file_logs["run_json"], use_container_width=True, hide_index=True, height=320)
    with st.expander(f"Napi JSONL gyártási napló ({len(file_logs['daily_jsonl'])})", expanded=False):
        if file_logs["daily_jsonl"].empty:
            st.info("Még nincs napi JSONL-napló.")
        else:
            st.dataframe(file_logs["daily_jsonl"], use_container_width=True, hide_index=True, height=320)
    with st.expander(f"Alkalmazás- és kezelői napló ({len(file_logs['application_log'])})", expanded=False):
        if file_logs["application_log"].empty:
            st.info("Még nincs alkalmazásnapló-bejegyzés.")
        else:
            st.dataframe(file_logs["application_log"], use_container_width=True, hide_index=True, height=320)

    export_dir = ROOT / "logs" / "exports"
    export_files = []
    if export_dir.exists():
        for item in sorted(export_dir.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True):
            export_files.append({
                "Fájlnév": item.name,
                "Méret (KB)": round(item.stat().st_size / 1024, 1),
                "Utoljára mentve": datetime.fromtimestamp(item.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "Elérési út": str(item),
            })
    with st.expander(f"Korábbi Excel-exportok ({len(export_files)})", expanded=False):
        if export_files:
            st.dataframe(pd.DataFrame(export_files), use_container_width=True, hide_index=True)
        else:
            st.info("Még nincs mentett Excel-export.")


def render_spot_grid(config: dict[str, Any], body_events: pd.DataFrame, completed: bool) -> tuple[int, int, int, int]:
    """Render a concise visual overview instead of a tall per-weld table."""
    latest_by_id: dict[str, pd.Series] = {}
    counts: dict[str, int] = {}
    if not body_events.empty:
        for _, row in body_events.sort_values("id").iterrows():
            weld_id = str(row["weld_id"])
            latest_by_id[weld_id] = row
            counts[weld_id] = counts.get(weld_id, 0) + 1
    html_cells: list[str] = []
    ok = waiting = bad = warn = 0
    for point in config["points"]:
        weld_id = str(point["weld_id"])
        row = latest_by_id.get(weld_id)
        count = counts.get(weld_id, 0)
        errors = json_list(row.get("errors_json", "[]")) if row is not None else []
        if count == 0:
            css, label = ("spot-bad", "Hiányzó") if completed else ("spot-wait", "Várakozik")
            if completed:
                bad += 1
            else:
                waiting += 1
        elif count > 1 or bool(row.get("duplicate", 0)):
            css, label = "spot-warn", "Duplikált"
            warn += 1
        elif errors:
            css, label = "spot-bad", "; ".join(errors)
            bad += 1
        else:
            css, label = "spot-ok", "Megfelelő"
            ok += 1
        order_label = f"{int(point['order']):03d}"
        html_cells.append(
            f'<span class="spot {css}" title="{html.escape(weld_id + " · " + label, quote=True)}">{order_label}</span>'
        )
    st.markdown('<div class="spot-grid">' + "".join(html_cells) + "</div>", unsafe_allow_html=True)
    return ok, waiting, bad, warn


# Use a fresh statistics window whenever the dashboard process is restarted.
# Historical records remain in SQLite and the history expander, not in current-run KPIs.
if st.session_state.get("app_process_id") != os.getpid():
    old_stop = st.session_state.get("auto_stop_event")
    if old_stop is not None:
        old_stop.set()
    st.session_state["app_process_id"] = os.getpid()
    st.session_state["app_session_started_at"] = time.time()
    st.session_state["app_session_id"] = uuid.uuid4().hex
    st.session_state.pop("auto_state", None)
    st.session_state.pop("auto_thread", None)
    st.session_state.pop("auto_stop_event", None)
if "auto_state" not in st.session_state:
    # Start in a genuinely idle state: the operator sets fault controls first,
    # then explicitly starts the automatic production from the live tab.
    st.session_state["auto_state"] = {
        "running": False, "completed_cycles": 0, "fault_rate": DEFAULT_FAULT_RATE,
        "fault_mode": "within_limits",
        "session_started_at": st.session_state.get("app_session_started_at", time.time()),
        "body_id": "", "config_id": "", "last_started_at": "", "last_sent_body_id": "",
        "error": None,
    }
    st.session_state["auto_stop_event"] = threading.Event()

header_left, header_right = st.columns([5.4, 1.2], vertical_alignment="center")
with header_left:
    st.markdown(
        """
        <div class="hero">
          <div>
            <div class="hero-title">BODYLINE <span style="color:#2457d6">/</span> Oldalfal-hegesztés</div>
            <div class="hero-sub">Ipar 4.0 · élő gyártási állapot · automatikus modellváltás · MQTT</div>
          </div>
          <div class="pill pill-live"><span class="dot"></span> SZIMULÁCIÓS CELLAFELÜGYELET</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with header_right:
    if st.session_state.get("logged_out"):
        st.button("✓  Munkamenet lezárva", key="logged_out_badge", disabled=True, use_container_width=True)
    elif st.button("⎋  Kijelentkezés + Excel", key="logout_export", type="primary", use_container_width=True):
        try:
            # Generate and persist the first Excel snapshot before waiting for any stop.
            report = make_excel_export(stop_automatic=True)
            st.session_state["logout_report"] = report
            st.session_state["logged_out"] = True
            st.session_state["logout_export_error"] = None
            st.rerun()
        except Exception as exc:
            safe_application_log("logout_export_failed", {"error": str(exc)}, level="ERROR")
            st.session_state["logout_export_error"] = str(exc)
            st.error(f"Nem sikerült elkészíteni az Excel-jelentést: {exc}")

if st.session_state.get("logout_export_error") and not st.session_state.get("logged_out"):
    st.error(
        "Az export nem készült el. Az adatbázis és a korábbi naplók megmaradnak; "
        f"próbáld újra a kijelentkezést. Részlet: {st.session_state['logout_export_error']}"
    )

if st.session_state.get("logged_out"):
    report = st.session_state.get("logout_report")
    st.markdown("## A munkamenet lezárult")
    st.success("A dátummal ellátott Excel-jelentés a lemezre mentve. A letöltéshez kattints az alábbi gombra.")
    if report:
        summary = report.get("summary", {})
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Oldalfalak", int(summary.get("session_body_count", 0)))
        r2.metric("Lezárt karosszériák", int(summary.get("session_completed_count", 0)))
        r3.metric("Megfelelt", int(summary.get("session_pass_count", 0)))
        r4.metric("Selejtes", int(summary.get("session_scrap_count", 0)))
        st.download_button(
            "⬇  Excel-jelentés letöltése",
            data=report["data"],
            file_name=report["filename"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_logout_report",
            type="primary",
            use_container_width=True,
        )
        st.code(report["path"])
        if report.get("automatic_worker_stopped"):
            st.caption("Az automatika leállt; a jelentés a leállás utáni utolsó adatokat is tartalmazza.")
        else:
            st.warning(
                "A gyártási szál a várakozási időn belül nem állt le. Az Excel ettől függetlenül elkészült, "
                "és a mentett adatbázist, valamint az export pillanatában folyamatban lévő oldalfal állapotát is tartalmazza. "
                "A további események továbbra is a naplófájlokba íródnak."
            )
    if st.button("Új munkamenet indítása", key="new_dashboard_session"):
        st.session_state["app_session_started_at"] = time.time()
        st.session_state["app_session_id"] = uuid.uuid4().hex
        st.session_state["logged_out"] = False
        st.session_state["logout_report"] = None
        st.session_state["logout_export_error"] = None
        st.session_state.pop("auto_state", None)
        st.session_state.pop("auto_thread", None)
        st.session_state.pop("auto_stop_event", None)
        st.rerun()
    st.stop()

production_tab, statistics_tab, log_tab = st.tabs([
    "◉  Élő gyártás", "▦  Statisztika és utómunka", "☷  Napló és export"
])


@st.fragment(run_every="1s")
def render_production_tab() -> None:
    all_bodies, events, all_rework, errors, actions = read_tables()
    bodies = session_bodies_only(all_bodies)
    session_ids = set(bodies["body_id"].astype(str)) if not bodies.empty else set()
    rework = all_rework[all_rework["body_id"].astype(str).isin(session_ids)].copy() if not all_rework.empty else all_rework
    auto_state = st.session_state["auto_state"]
    stop_event = st.session_state["auto_stop_event"]
    worker = st.session_state.get("auto_thread")
    worker_alive = worker is not None and worker.is_alive()
    running = bool(auto_state.get("running")) and not stop_event.is_set()

    head_left, head_right = st.columns([5, 1.3], vertical_alignment="center")
    with head_left:
        st.markdown("## Gyártócella élő nézete")
        st.caption(f"Karosszéria-hegesztés 20 mp alatt · két karosszéria között {BETWEEN_BODIES_PAUSE_SECONDS:.0f} mp szünet · automatikus modellválasztás")
    with head_right:
        if running:
            if st.button("Ⅱ  Automatika leállítása", key="stop_auto", use_container_width=True):
                stop_event.set()
                auto_state["running"] = False
                safe_application_log("automatic_production_stop_requested", {
                    "body_id": auto_state.get("body_id", ""),
                    "completed_cycles": auto_state.get("completed_cycles", 0),
                })
                st.toast("Az automatikus gyártás leállítási kérése rögzítve.")
                st.rerun(scope="fragment")
        elif worker_alive:
            st.button(
                "… Gyártási ciklus lezárása",
                key="auto_stopping",
                disabled=True,
                use_container_width=True,
                help="A már megkezdett karosszéria feldolgozása biztonságosan befejeződik.",
            )
        else:
            if st.button("▶  Automatika indítása", key="start_auto", type="primary", use_container_width=True):
                start_automatic_production()
                st.rerun(scope="fragment")

    total = len(bodies)
    completed = bodies[~bodies["status"].eq("FOLYAMATBAN")] if total else pd.DataFrame()
    good_count = int(completed["status"].eq("MEGFELELŐ").sum()) if not completed.empty else 0
    failed_count = int(completed["status"].astype(str).str.contains("SELEJT").sum()) if not completed.empty else 0
    open_count = int((rework["status"] != REWORK_DONE).sum()) if not rework.empty else 0
    pass_pct = (100 * good_count / len(completed)) if not completed.empty else 100.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Feldolgozott oldalfalak", f"{total:,}".replace(",", " "))
    k2.metric("Megfelelt", f"{good_count:,}".replace(",", " "), delta=f"{pass_pct:.1f}% megfelelési arány")
    k3.metric("Selejtes oldalfalak (db)", f"{failed_count:,}".replace(",", " "))
    k4.metric("Nyitott utómunka", f"{open_count:,}")

    body_id = str(auto_state.get("body_id") or "")
    config_id = str(auto_state.get("config_id") or "")
    current_row = None
    if not bodies.empty:
        if body_id:
            rows = bodies[bodies["body_id"].astype(str).eq(body_id)]
            if not rows.empty:
                current_row = rows.iloc[0]
        if current_row is None:
            in_progress = bodies[bodies["status"].eq("FOLYAMATBAN")]
            current_row = in_progress.iloc[0] if not in_progress.empty else bodies.iloc[0]
        body_id = str(current_row["body_id"])
        config_id = str(current_row.get("config_id") or config_id)
    config = CONFIG_BY_ID.get(config_id) or CATALOG[0]
    body_events = events[events["body_id"].astype(str).eq(body_id)].copy() if body_id and not events.empty else pd.DataFrame()
    if not body_events.empty:
        body_events = body_events.sort_values("id")
    seen = set(body_events["weld_id"].astype(str)) if not body_events.empty else set()
    expected = int(config["expected_count"])
    progress = min(1.0, len(seen.intersection(config["expected_weld_ids"])) / expected) if expected else 0.0
    body_status = str(current_row["status"]) if current_row is not None else "VÁRAKOZÁS"
    is_complete = body_status != "FOLYAMATBAN" and body_status != "VÁRAKOZÁS" and bool(body_id)

    state_class = "pill-live" if running else "pill-off"
    state_text = "AUTOMATIKUS ÜZEM" if running else "SZÜNETEL"
    model_label = f'{config["brand"]} {config["model"]}'
    st.markdown(
        f"""
        <div class="hero" style="margin-top:.65rem;padding:.8rem 1rem">
          <div>
            <div class="hero-title" style="font-size:1.05rem">{html.escape(model_label)} <span style="color:#96a4b8">/</span> Bal oldalfal</div>
            <div class="hero-sub">Azonosító: {html.escape(body_id or "Első karosszériára vár")} · Utolsó indítás: {html.escape(str(auto_state.get("last_started_at") or "—"))}</div>
          </div>
          <div class="pill {state_class}"><span class="dot"></span> {state_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if auto_state.get("error"):
        st.warning(f"MQTT-küldési hiba: {auto_state['error']} — ellenőrizd, hogy fut-e a Docker Desktop és a monitor.")
    st.progress(progress, text=f"Pontteljesség  {len(seen.intersection(config['expected_weld_ids']))} / {expected}  ·  {progress:.0%}")
    duration_value = current_row.get("duration_seconds") if current_row is not None else None
    if duration_value is not None and pd.notna(duration_value):
        duration_text = f"Utolsó ciklusidő: {float(duration_value):.2f} mp · cél: 20 mp alatt"
    else:
        duration_text = "Ciklusidő: feldolgozás alatt · cél: 20 mp alatt"
    st.caption(duration_text)

    latest = body_events.iloc[-1] if not body_events.empty else None
    metric_cols = st.columns(4)
    if latest is None:
        values = [("Utolsó hegesztési pont", "—"), ("Áramerősség", "Várakozik"), ("Hegesztési idő", "—"), ("Elektródaerő", "—")]
    else:
        values = [
            ("Utolsó hegesztési pont", str(latest["weld_id"])),
            ("Áramerősség", f"{latest['current_ka']} kA" if pd.notna(latest["current_ka"]) else "Hiányzik"),
            ("Hegesztési idő", f"{latest['weld_time_ms']} ms" if pd.notna(latest["weld_time_ms"]) else "Hiányzik"),
            ("Elektródaerő", f"{latest['electrode_force_kn']} kN" if pd.notna(latest["electrode_force_kn"]) else "Hiányzik"),
        ]
    for col, (label, value) in zip(metric_cols, values):
        col.markdown(
            f'<div class="reading"><div><div class="reading-label">{html.escape(label)}</div>'
            f'<div class="reading-value">{html.escape(value)}</div></div></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-label">Oldalfal hegesztési ponttérképe</div>', unsafe_allow_html=True)
    ok, waiting, bad, warn = render_spot_grid(config, body_events, is_complete)
    st.markdown(
        f"""
        <div class="legend">
          <span><i style="background:#dff7ed"></i>{ok} rendben</span>
          <span><i style="background:#edf1f6"></i>{waiting} várakozik</span>
          <span><i style="background:#ffe5e8"></i>{bad} hiányzó/hibás</span>
          <span><i style="background:#fff1ce"></i>{warn} duplikált</span>
          <span class="compact-note">Összesen {expected} pont · a szám a pont sorrendjét jelöli</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not running and not stop_event.is_set():
        st.info("Az automatikus üzem elindulhat a fenti gombbal.")
    st.caption("Oktatási célú szimuláció: a pontlista és a határértékek szintetikusak, nem gyártói specifikációk.")


@st.fragment(run_every="2s")
def render_statistics_tab() -> None:
    all_bodies, all_events, all_rework, all_errors, all_actions = read_tables()
    bodies = session_bodies_only(all_bodies)
    session_ids = set(bodies["body_id"].astype(str)) if not bodies.empty else set()
    events = all_events[all_events["body_id"].astype(str).isin(session_ids)].copy() if not all_events.empty else all_events
    rework = all_rework[all_rework["body_id"].astype(str).isin(session_ids)].copy() if not all_rework.empty else all_rework
    errors = all_errors
    actions = all_actions[all_actions["body_id"].astype(str).isin(session_ids)].copy() if not all_actions.empty else all_actions
    st.markdown("## Minőségügyi áttekintés")
    st.caption("A fő statisztika csak a mostani böngésző-munkamenetben indult oldalfalakat számolja; a korábbi futások az előzményekben maradnak.")
    # This control panel must remain visible even before the first body exists.
    render_fault_controls()
    if bodies.empty:
        st.info("Az adatbázis még nem kapott karosszéria-eseményt. Ellenőrizd a Docker MQTT-brokert és a python -m src.monitor folyamatot.")
        return

    completed = bodies[~bodies["status"].eq("FOLYAMATBAN")].copy()
    good = int(completed["status"].eq("MEGFELELŐ").sum()) if not completed.empty else 0
    failed = int(completed["status"].astype(str).str.contains("SELEJT").sum()) if not completed.empty else 0
    pass_pct = 100 * good / len(completed) if not completed.empty else 100.0
    open_rework = int((rework["status"] != REWORK_DONE).sum()) if not rework.empty else 0
    avg_points = float(completed["expected_count"].mean()) if not completed.empty and "expected_count" in completed else 0.0

    scrap_pct = 100 * failed / len(completed) if len(completed) else 0.0
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Összes oldalfal", f"{len(bodies):,}".replace(",", " "))
    m2.metric("Megfelelt oldalfalak", f"{good:,}".replace(",", " "))
    m3.metric("Selejtes oldalfalak (db)", f"{failed:,}".replace(",", " "))
    m4.metric("Megfelelési arány", f"{pass_pct:.1f}%")
    m5.metric("Selejtarány", f"{scrap_pct:.1f}%")
    st.caption(f"Átlagos elvárt hegesztési pontszám: {avg_points:.1f} pont/oldalfal.")

    chart_left, chart_right = st.columns([1.2, 1])
    with chart_left:
        st.markdown("### Gyártási eredmények modellenként")
        if "config_id" in bodies:
            model_counts = bodies.groupby("config_id")["status"].value_counts().unstack(fill_value=0)
            chart_rows = []
            for config_id, row in model_counts.iterrows():
                cfg = CONFIG_BY_ID.get(str(config_id))
                chart_rows.append({
                    "Modell": f'{cfg["brand"]} {cfg["model"]}' if cfg else str(config_id),
                    "Megfelelt": int(row.get("MEGFELELŐ", 0)),
                    "Utómunka": int(row.get("SELEJT / UTÓMUNKÁRA KÜLDVE", 0)),
                })
            if chart_rows:
                st.bar_chart(pd.DataFrame(chart_rows).set_index("Modell"), height=260)
    with chart_right:
        st.markdown("### Minőségi állapotok")
        status_counts = completed["status"].value_counts().rename_axis("Állapot").reset_index(name="Darab")
        if status_counts.empty:
            st.caption("Még nincs lezárt karosszéria.")
        else:
            st.dataframe(status_counts, use_container_width=True, hide_index=True, height=260)


    st.markdown("### Automatikus utómunka-sor")
    if rework.empty:
        st.success("Jelenleg nincs utómunka-bejegyzés.")
    else:
        a, b, c = st.columns(3)
        a.metric("Összes utómunka-eset", len(rework))
        b.metric("Nyitott esetek", open_rework)
        c.metric("Adminisztratívan lezárt", int(rework["status"].eq(REWORK_DONE).sum()))
        active = rework[rework["status"] != REWORK_DONE]
        st.dataframe(
            active[["body_id", "reason", "status", "created_at"]].head(30),
            use_container_width=True, hide_index=True, height=190,
        )
        if not active.empty:
            options = {
                f'{row["body_id"]} — {row["status"]}': row
                for _, row in active.iterrows()
            }
            selected_label = st.selectbox("Kezelendő utómunka", list(options), key="selected_rework")
            item = options[selected_label]
            note = st.text_input("Operátori megjegyzés", key=f"rework_note_{item['body_id']}")
            left, right = st.columns(2)
            if item["status"] == REWORK_WAITING:
                if left.button("Utómunka megkezdése", key=f"rework_start_{item['body_id']}", use_container_width=True):
                    try:
                        publish_control_event({"event_type": "rework_action", "body_id": str(item["body_id"]),
                            "action": "START", "note": note, "timestamp": pd.Timestamp.now(tz="UTC").isoformat()})
                        st.toast("Utómunka megkezdését elküldtem.")
                    except Exception as exc:
                        st.error(f"Az utómunka nem indítható: {exc}")
            elif item["status"] == REWORK_IN_PROGRESS:
                if left.button("Utómunka kész — újraellenőrzés", key=f"rework_complete_{item['body_id']}", type="primary", use_container_width=True):
                    try:
                        publish_control_event({"event_type": "rework_action", "body_id": str(item["body_id"]),
                            "action": "COMPLETE", "note": note, "timestamp": pd.Timestamp.now(tz="UTC").isoformat()})
                        st.toast("Utómunka lezárási esemény elküldve.")
                    except Exception as exc:
                        st.error(f"Az utómunka nem zárható le: {exc}")
            right.caption("Az utómunka lezárása nem írja át automatikusan a selejtes minősítést.")

    with st.expander("Karosszéria-előzmények", expanded=False):
        history = all_bodies.copy()
        for source, label in [
            ("missing_ids_json", "Hiányzó pontok"),
            ("unexpected_ids_json", "Váratlan pontok"),
            ("duplicate_ids_json", "Duplikált pontok"),
        ]:
            if source in history:
                history[label] = history[source].apply(lambda value: ", ".join(json_list(value)))
        cols = [c for c in [
            "body_id", "config_id", "body_type", "expected_count", "event_count", "status",
            "parameter_errors", "latency_ms", "Hiányzó pontok", "Váratlan pontok",
            "Duplikált pontok", "started_at", "completed_at",
        ] if c in history]
        st.dataframe(history[cols].head(50), use_container_width=True, hide_index=True, height=250)

    with st.expander("Mérési napló – legutóbbi 100 hegesztés", expanded=False):
        if events.empty:
            st.caption("Még nincs mérési adat.")
        else:
            cols = [c for c in [
                "timestamp", "body_id", "config_id", "weld_id", "current_ka",
                "weld_time_ms", "electrode_force_kn", "errors_json", "duplicate",
            ] if c in events]
            st.dataframe(events[cols].head(100), use_container_width=True, hide_index=True, height=300)

    with st.expander("Utómunka-eseménynapló", expanded=False):
        if actions.empty:
            st.caption("Még nincs utómunka-művelet.")
        else:
            st.dataframe(actions[["timestamp", "body_id", "action", "note"]].head(100),
                         use_container_width=True, hide_index=True, height=220)

    with st.expander("MQTT- és feldolgozási hibák", expanded=False):
        if errors.empty:
            st.success("Nincs naplózott feldolgozási hiba.")
        else:
            st.dataframe(errors[["received_at", "category", "detail", "raw_payload"]].head(50),
                         use_container_width=True, hide_index=True, height=220)


with production_tab:
    render_production_tab()

with statistics_tab:
    render_statistics_tab()

with log_tab:
    render_complete_log_tab()
