"""Streamlit dashboard for simulated welding runs."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.simulator import BODY_TYPES, generate_body_events, publish_events
from src.monitor import DB_PATH

st.set_page_config(page_title="Karosszéria-hegesztés | Ipar 4.0", page_icon="🏭", layout="wide")
st.title("Karosszéria-ponthegesztési szimulátor")
st.caption("Ipar 4.0 demonstráció • MQTT-adatközvetítés • szimulált folyamatadatok")
st.warning("Oktatási szimuláció: a küszöbértékek és az adatok nem valódi Audi-mérések, a felület nem igazol fizikai hegesztési minőséget.")

with st.sidebar:
    st.header("Szimuláció beállításai")
    body_type = st.selectbox("Karosszériatípus", list(BODY_TYPES.keys()))
    fault_rate = st.slider("Hibák valószínűsége", 0.0, 0.30, 0.06, 0.01)
    delay_ms = st.slider("Üzenetek közötti késleltetés (ms)", 0, 50, 5, 1)
    st.markdown("**Szimulált paraméterek**")
    st.write("Áramerősség: 7–11 kA")
    st.write("Hegesztési idő: 150–350 ms")
    st.write("Elektródaerő: 2,5–4,5 kN")

if st.button("▶ Szimuláció indítása", type="primary", use_container_width=True):
    try:
        with st.spinner("Események generálása és publikálása MQTT-n..."):
            body_id, events = generate_body_events(body_type, fault_rate)
            publish_events(events, delay_ms=delay_ms)
        st.session_state["last_body_id"] = body_id
        st.success(f"Elküldve: {body_id}. A monitor néhány pillanat múlva feldolgozza az adatokat.")
        time.sleep(0.5)
    except (OSError, RuntimeError, TimeoutError) as exc:
        st.error(f"Nem sikerült MQTT-re publikálni. Ellenőrizd, hogy fut-e a broker: {exc}")

@st.cache_data(ttl=2)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not DB_PATH.exists():
        return pd.DataFrame(), pd.DataFrame()
    with sqlite3.connect(DB_PATH) as conn:
        bodies = pd.read_sql_query("SELECT * FROM bodies ORDER BY started_at DESC", conn)
        events = pd.read_sql_query("SELECT * FROM weld_events ORDER BY id DESC LIMIT 500", conn)
    return bodies, events

if st.button("↻ Adatok frissítése"):
    load_data.clear()
bodies, events = load_data()
if bodies.empty:
    st.info("Még nincs feldolgozott adat. Indítsd el a Mosquitto brokert és a monitor modult, majd futtass egy szimulációt.")
else:
    completed = bodies[bodies["completed_at"].notna()]
    bad = completed[completed["status"] != "MEGFELELŐ"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Karosszériák", len(bodies))
    c2.metric("Lezárt futások", len(completed))
    c3.metric("Ellenőrizendő / selejt", len(bad))
    c4.metric("Beérkezett hegesztési esemény", int(events.shape[0]))
    st.subheader("Karosszériák állapota")
    display = bodies.copy()
    display["Hiányzó pontok"] = display["missing_ids_json"].apply(lambda x: ", ".join(json.loads(x or "[]")))
    display["Duplikált pontok"] = display["duplicate_ids_json"].apply(lambda x: ", ".join(json.loads(x or "[]")))
    st.dataframe(display[["body_id", "body_type", "expected_count", "event_count", "status", "parameter_errors", "Hiányzó pontok", "Duplikált pontok", "started_at"]], use_container_width=True, hide_index=True)
    if not bad.empty:
        st.subheader("Ellenőrzendő karosszériák")
        st.dataframe(bad[["body_id", "body_type", "status", "missing_ids_json", "duplicate_ids_json", "parameter_errors"]], use_container_width=True, hide_index=True)
    st.subheader("Legutóbbi hegesztési események")
    if not events.empty:
        st.dataframe(events[["body_id", "weld_id", "current_ka", "weld_time_ms", "electrode_force_kn", "duplicate", "errors_json", "timestamp"]], use_container_width=True, hide_index=True)

st.divider()
st.caption("Adatút: publisher → Mosquitto MQTT broker → monitor/ellenőrző → SQLite → dashboard. A dashboard frissítéséhez használd az Adatok frissítése gombot.")
