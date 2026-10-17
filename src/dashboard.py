"""Modern, compact two-tab Streamlit dashboard for automatic sidewall welding simulation."""
from __future__ import annotations

import html
import json
import os
import random
import sqlite3
import threading
import time
import uuid
from pathlib import Path
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
from src.simulator import generate_body_events, publish_events

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
            body_id, events = generate_body_events(
                config_id,
                fault_rate=float(state.get("fault_rate", DEFAULT_FAULT_RATE)),
                fault_mode=str(state.get("fault_mode", "within_limits")),
            )
            state["body_id"] = body_id
            state["config_id"] = config_id
            state["last_started_at"] = pd.Timestamp.now().strftime("%H:%M:%S")
            state["error"] = None
            publish_events(events, delay_ms=PUBLISH_DELAY_MS)
            state["completed_cycles"] = int(state.get("completed_cycles", 0)) + 1
            state["last_sent_body_id"] = body_id
        except Exception as exc:
            state["error"] = str(exc)
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


def start_automatic_production() -> None:
    """Start the cycle worker once per Streamlit session."""
    old_thread = st.session_state.get("auto_thread")
    old_stop = st.session_state.get("auto_stop_event")
    if old_thread is not None and old_thread.is_alive() and old_stop is not None and not old_stop.is_set():
        return
    if old_thread is not None and old_thread.is_alive() and old_stop is not None:
        old_thread.join(timeout=1.0)
    stop_event = threading.Event()
    state = {
        "running": True, "completed_cycles": 0, "fault_rate": DEFAULT_FAULT_RATE,
        "fault_mode": "within_limits",
        "session_started_at": st.session_state.get("app_session_started_at", time.time()),
        "body_id": "", "config_id": "", "last_started_at": "", "last_sent_body_id": "",
        "error": None,
    }
    worker = threading.Thread(
        target=automatic_production_worker, args=(stop_event, state, list(CONFIG_BY_ID)),
        name="automatic-welding-production", daemon=True,
    )
    st.session_state["auto_stop_event"] = stop_event
    st.session_state["auto_state"] = state
    st.session_state["auto_thread"] = worker
    worker.start()


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

# Reset the dashboard's statistics window when the Python process or dashboard source changes.
# This stops historical rejected bodies from appearing as failures in the new run.
_code_mtime = Path(__file__).stat().st_mtime
if (
    st.session_state.get("app_process_id") != os.getpid()
    or st.session_state.get("app_code_mtime") != _code_mtime
):
    st.session_state["app_process_id"] = os.getpid()
    st.session_state["app_code_mtime"] = _code_mtime
    st.session_state["app_session_started_at"] = time.time()
    st.session_state["app_session_id"] = uuid.uuid4().hex
    st.session_state.pop("auto_state", None)
if "auto_state" not in st.session_state:
    start_automatic_production()

production_tab, statistics_tab = st.tabs(["◉  Élő gyártás", "▦  Statisztika és utómunka"])


@st.fragment(run_every="1s")
def render_production_tab() -> None:
    all_bodies, events, all_rework, errors, actions = read_tables()
    bodies = session_bodies_only(all_bodies)
    session_ids = set(bodies["body_id"].astype(str)) if not bodies.empty else set()
    rework = all_rework[all_rework["body_id"].astype(str).isin(session_ids)].copy() if not all_rework.empty else all_rework
    auto_state = st.session_state["auto_state"]
    stop_event = st.session_state["auto_stop_event"]
    running = bool(auto_state.get("running")) and not stop_event.is_set()

    head_left, head_right = st.columns([5, 1.3], vertical_alignment="center")
    with head_left:
        st.markdown("## Gyártócella élő nézete")
        st.caption(f"Karosszéria-hegesztés 20 mp alatt · két karosszéria között {BETWEEN_BODIES_PAUSE_SECONDS:.0f} mp szünet · automatikus modellválasztás")
    with head_right:
        if running:
            if st.button("Ⅱ  Automatika leállítása", key="stop_auto", use_container_width=True):
                stop_event.set()
                st.toast("Az automatikus gyártás leállítása elküldve.")
                st.rerun(scope="fragment")
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
    k3.metric("Utómunka / selejt", f"{failed_count:,}".replace(",", " "))
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
    if bodies.empty:
        st.info("Az adatbázis még nem kapott karosszéria-eseményt. Ellenőrizd a Docker MQTT-brokert és a python -m src.monitor folyamatot.")
        return

    completed = bodies[~bodies["status"].eq("FOLYAMATBAN")].copy()
    good = int(completed["status"].eq("MEGFELELŐ").sum()) if not completed.empty else 0
    failed = int(completed["status"].astype(str).str.contains("SELEJT").sum()) if not completed.empty else 0
    pass_pct = 100 * good / len(completed) if not completed.empty else 100.0
    open_rework = int((rework["status"] != REWORK_DONE).sum()) if not rework.empty else 0
    avg_points = float(completed["expected_count"].mean()) if not completed.empty and "expected_count" in completed else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Összes oldalfal", len(bodies))
    m2.metric("Megfelelési arány", f"{pass_pct:.1f}%")
    m3.metric("Selejtarány", f"{100 * failed / len(completed):.1f}%" if len(completed) else "0.0%")
    m4.metric("Átlagos elvárt pontszám", f"{avg_points:.1f}")

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
        st.markdown("### Pontonkénti eltérés beállítása")
        fault_rate_percent = st.slider(
            "Egy hegesztési pont eltérésének esélye (%)",
            min_value=0.0,
            max_value=0.1,
            value=0.0,
            step=0.001,
            format="%.3f%%",
            key="fault_rate_percent_v3",
            help="0,000% esetén nem kerül be mesterséges eltérés. A beállítás pontonként értendő, nem karosszériánként.",
        )
        fault_mode_label = st.selectbox(
            "Az eltérés viselkedése",
            options=[
                "Megengedett tartományon belül marad (megfelelő)",
                "Átlépi a határértéket (utómunka)",
            ],
            index=0,
            key="fault_mode_choice_v3",
            help=(
                "Az első mód a mérést a megengedett alsó vagy felső határ közelébe viszi, de nem lépi át. "
                "A második mód egy kis lépéssel a határon kívülre állít egy paramétert."
            ),
        )
        st.session_state["auto_state"]["fault_rate"] = float(fault_rate_percent) / 100.0
        st.session_state["auto_state"]["fault_mode"] = (
            "outside_limits"
            if fault_mode_label.startswith("Átlépi")
            else "within_limits"
        )
        st.caption(
            f"Pontonkénti esély: {fault_rate_percent:.3f}% · "
            f"{'a kiválasztott pont továbbra is megfelelő' if st.session_state['auto_state']['fault_mode'] == 'within_limits' else 'az eltérés határon kívülre kerül'}."
        )

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
