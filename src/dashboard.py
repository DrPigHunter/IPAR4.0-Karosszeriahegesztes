"""Live Streamlit UI for a simulated automotive spot-welding line."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import paho.mqtt.client as mqtt
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.monitor import (
    BROKER_HOST, BROKER_PORT, DB_PATH, REWORK_DONE,
    REWORK_IN_PROGRESS, REWORK_WAITING, TOPIC,
)
from src.simulator import BODY_TYPES, generate_body_events, publish_events

st.set_page_config(page_title="Karosszéria-hegesztés | Ipar 4.0", page_icon="🏭", layout="wide")
st.title("Karosszéria-ponthegesztési felügyelet")
st.caption("Élő szimulált gyártócella · MQTT-adatút · hegesztési pontok és utómunka követése")
st.warning(
    "Oktatási szimuláció: az értékek és határértékek mesterségesek, nem valódi Audi-adatok. "
    "A paraméterellenőrzés nem bizonyítja a fizikai hegesztési kötés mechanikai szilárdságát."
)


def publish_control_event(event: dict[str, Any]) -> None:
    """Send operator actions through MQTT too, so the monitor owns state transitions."""
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
            raise RuntimeError(f"Az MQTT-műveletet nem sikerült visszaigazolni (rc={info.rc}).")
    finally:
        client.loop_stop()
        client.disconnect()


def read_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not DB_PATH.exists():
        return tuple(pd.DataFrame() for _ in range(5))  # type: ignore[return-value]
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        bodies = pd.read_sql_query("SELECT * FROM bodies ORDER BY started_at DESC", conn)
        events = pd.read_sql_query("SELECT * FROM weld_events ORDER BY id DESC LIMIT 500", conn)
        rework = pd.read_sql_query("SELECT * FROM rework_queue ORDER BY created_at DESC", conn)
        errors = pd.read_sql_query("SELECT * FROM system_errors ORDER BY id DESC LIMIT 100", conn)
        actions = pd.read_sql_query("SELECT * FROM rework_actions ORDER BY id DESC LIMIT 100", conn)
    return bodies, events, rework, errors, actions


with st.sidebar:
    st.header("Gyártási szimuláció")
    body_type = st.selectbox("Karosszériatípus", list(BODY_TYPES.keys()))
    fault_rate = st.slider("Hibák valószínűsége", 0.0, 0.30, 0.06, 0.01)
    delay_ms = st.slider("Üzenetek közötti késleltetés (ms)", 0, 50, 5, 1)
    st.caption("Pontok száma: " + str(BODY_TYPES[body_type]))
    st.markdown("**Szimulált technológiai határok**")
    st.write("Áramerősség: 7–11 kA")
    st.write("Hegesztési idő: 150–350 ms")
    st.write("Elektródaerő: 2,5–4,5 kN")
    st.divider()
    if st.button("▶ Új karosszéria indítása", type="primary", use_container_width=True):
        try:
            body_id, generated = generate_body_events(body_type, fault_rate)
            with st.spinner(f"{body_id} üzeneteinek küldése MQTT-n..."):
                publish_events(generated, delay_ms=delay_ms)
            st.session_state["last_body_id"] = body_id
            st.success(f"Elindítva: {body_id}")
        except Exception as exc:
            st.error(f"Nem sikerült elindítani a szimulációt: {exc}")
    st.caption("Az élő nézet automatikusan, 2 másodpercenként frissül.")


def json_list(value: Any) -> list[str]:
    try:
        result = json.loads(value or "[]")
        return [str(x) for x in result] if isinstance(result, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


@st.fragment(run_every="2s")
def live_monitor_panel() -> None:
    try:
        bodies, events, rework, errors, actions = read_tables()
    except (sqlite3.Error, pd.errors.DatabaseError) as exc:
        st.error(f"Az adatbázis nem olvasható. Ellenőrizd, hogy fut-e a monitor: {exc}")
        return

    if bodies.empty:
        st.info("Várakozás az első karosszériára. Indítsd el a brokert és a monitort, majd a bal oldali panelen egy szimulációt.")
        return

    in_progress = bodies[bodies["status"] == "FOLYAMATBAN"]
    current = in_progress.iloc[0] if not in_progress.empty else bodies.iloc[0]
    body_id = str(current["body_id"])
    expected_ids = json_list(current.get("expected_ids_json", "[]"))
    body_events = events[events["body_id"] == body_id].copy() if not events.empty else pd.DataFrame()
    if not body_events.empty:
        # The event table is loaded newest-first; restore chronological order for the point map.
        body_events = body_events.sort_values("id")

    counts = body_events["weld_id"].astype(str).value_counts().to_dict() if not body_events.empty else {}
    seen_expected = len(set(counts).intersection(expected_ids))
    expected_count = int(current.get("expected_count", len(expected_ids)) or len(expected_ids))
    progress = min(seen_expected / expected_count, 1.0) if expected_count else 0.0
    is_active = str(current["status"]) == "FOLYAMATBAN"

    st.subheader("Aktuális karosszéria a gyártócella végén")
    top1, top2, top3, top4, top5 = st.columns(5)
    top1.metric("Karosszéria-azonosító", body_id)
    top2.metric("Típus", str(current["body_type"]))
    top3.metric("Beérkezett pontok", f"{seen_expected} / {expected_count}")
    top4.metric("Hegesztési üzenetek", len(body_events))
    top5.metric("Paraméterhibák", int(current.get("parameter_errors", 0) or 0))
    st.progress(progress, text=f"Pontteljesség: {progress:.0%} · {'HEGESZTÉS FOLYAMATBAN' if is_active else str(current['status'])}")

    if is_active:
        st.info("A karosszéria még folyamatban van. A hegesztési értékek és a ponttérkép üzenetenként frissülnek.")
    elif str(current["status"]) == "MEGFELELŐ":
        st.success("A karosszéria megfelelt a szimulált ellenőrzésnek.")
    else:
        st.error("SELEJT: a rendszer automatikusan utómunka-sorra helyezte.")

    latest = body_events.iloc[-1] if not body_events.empty else None
    st.markdown("**Legutóbb beérkezett hegesztési mérés**")
    m1, m2, m3, m4 = st.columns(4)
    if latest is None:
        m1.metric("Hegesztési pont", "Még nincs adat")
        m2.metric("Áramerősség", "—")
        m3.metric("Hegesztési idő", "—")
        m4.metric("Elektródaerő", "—")
    else:
        m1.metric("Hegesztési pont", str(latest["weld_id"]))
        m2.metric("Áramerősség", f"{latest['current_ka']} kA" if pd.notna(latest["current_ka"]) else "HIÁNYZIK")
        m3.metric("Hegesztési idő", f"{latest['weld_time_ms']} ms" if pd.notna(latest["weld_time_ms"]) else "HIÁNYZIK")
        m4.metric("Elektródaerő", f"{latest['electrode_force_kn']} kN" if pd.notna(latest["electrode_force_kn"]) else "HIÁNYZIK")

    # Build an operator-friendly map: every expected point has an explicit state.
    point_records: list[dict[str, Any]] = []
    for weld_id in expected_ids:
        matching = body_events[body_events["weld_id"].astype(str) == weld_id] if not body_events.empty else pd.DataFrame()
        count = len(matching)
        newest = matching.iloc[-1] if count else None
        point_errors = json_list(newest["errors_json"]) if newest is not None else []
        if count == 0:
            point_status, icon_text = ("FOLYAMATBAN", "⏳") if is_active else ("HIÁNYZIK", "❌")
        elif count > 1 or (newest is not None and bool(newest["duplicate"])):
            point_status, icon_text = "DUPLIKÁLT", "⚠️"
        elif point_errors:
            point_status, icon_text = "PARAMÉTERHIBA", "❌"
        else:
            point_status, icon_text = "MEGFELELŐ", "✅"
        point_records.append({
            "Pont": weld_id, "Állapot": point_status, "Üzenetek": count,
            "Áramerősség (kA)": newest["current_ka"] if newest is not None else None,
            "Hegesztési idő (ms)": newest["weld_time_ms"] if newest is not None else None,
            "Elektródaerő (kN)": newest["electrode_force_kn"] if newest is not None else None,
            "Hiba / megjegyzés": "; ".join(point_errors),
            "_map_label": f"{icon_text} {weld_id}",
        })
    expected_set = set(expected_ids)
    for weld_id in sorted(set(counts) - expected_set):
        matching = body_events[body_events["weld_id"].astype(str) == weld_id]
        newest = matching.iloc[-1]
        point_records.append({
            "Pont": weld_id, "Állapot": "VÁRATLAN PONT", "Üzenetek": len(matching),
            "Áramerősség (kA)": newest["current_ka"], "Hegesztési idő (ms)": newest["weld_time_ms"],
            "Elektródaerő (kN)": newest["electrode_force_kn"],
            "Hiba / megjegyzés": "A pont nem szerepel a karosszériatípus elvárt listájában.",
            "_map_label": f"⚠️ {weld_id}",
        })

    st.markdown("**Hegesztési ponttérkép** — ✅ rendben · ⏳ még nem érkezett meg · ❌ hiányzó/paraméterhiba · ⚠️ duplikált/váratlan")
    map_labels = [row["_map_label"] for row in point_records]
    if map_labels:
        grid_width = 10
        grid = [map_labels[i:i + grid_width] for i in range(0, len(map_labels), grid_width)]
        grid_df = pd.DataFrame([row + [""] * (grid_width - len(row)) for row in grid],
                               columns=[f"Pontcsoport {i + 1}" for i in range(grid_width)])
        st.dataframe(grid_df, use_container_width=True, hide_index=True, height=min(430, 36 * (len(grid) + 1)))
    with st.expander("Összes pont részletes paraméterei", expanded=False):
        if point_records:
            details = pd.DataFrame(point_records).drop(columns=["_map_label"])
            st.dataframe(details, use_container_width=True, hide_index=True, height=360)

    st.subheader("Karosszériák és ellenőrzési eredmények")
    history = bodies.copy()
    for source, label in [
        ("missing_ids_json", "Hiányzó pontok"),
        ("unexpected_ids_json", "Váratlan pontok"),
        ("duplicate_ids_json", "Duplikált pontok"),
    ]:
        history[label] = history[source].apply(lambda x: ", ".join(json_list(x)))
    hist_cols = ["body_id", "body_type", "expected_count", "event_count", "status",
                 "parameter_errors", "latency_ms", "Hiányzó pontok", "Váratlan pontok",
                 "Duplikált pontok", "started_at", "completed_at"]
    st.dataframe(history[hist_cols], use_container_width=True, hide_index=True, height=230)

    st.subheader("Automatikus utómunka-sor")
    if rework.empty:
        st.success("Jelenleg nincs selejtes karosszéria az utómunka-soron.")
    else:
        active_rework = rework[rework["status"] != REWORK_DONE]
        r1, r2, r3 = st.columns(3)
        r1.metric("Összes utómunka-eset", len(rework))
        r2.metric("Nyitott esetek", len(active_rework))
        r3.metric("Lezárt utómunkák", int((rework["status"] == REWORK_DONE).sum()))
        st.dataframe(rework[["body_id", "reason", "status", "created_at", "updated_at", "resolution_note"]],
                     use_container_width=True, hide_index=True)
        for _, item in rework.iterrows():
            queue_body_id = str(item["body_id"])
            with st.expander(f"{queue_body_id} — {item['status']}"):
                st.write("**Hiba oka:** " + str(item["reason"]))
                note = st.text_input("Utómunka megjegyzése", key=f"note_{queue_body_id}")
                if item["status"] == REWORK_WAITING:
                    if st.button("Utómunka megkezdése", key=f"start_{queue_body_id}"):
                        try:
                            publish_control_event({"event_type": "rework_action", "body_id": queue_body_id,
                                                   "action": "START", "note": note, "timestamp": pd.Timestamp.now(tz="UTC").isoformat()})
                            st.toast("Az utómunka megkezdését rögzítettem MQTT-n.")
                        except Exception as exc:
                            st.error(f"Nem sikerült rögzíteni az utómunkát: {exc}")
                elif item["status"] == REWORK_IN_PROGRESS:
                    if st.button("Utómunka kész — újraellenőrzés szükséges", key=f"complete_{queue_body_id}"):
                        try:
                            publish_control_event({"event_type": "rework_action", "body_id": queue_body_id,
                                                   "action": "COMPLETE", "note": note, "timestamp": pd.Timestamp.now(tz="UTC").isoformat()})
                            st.toast("Az utómunka lezárva; a karosszéria újraellenőrzésre vár.")
                        except Exception as exc:
                            st.error(f"Nem sikerült lezárni az utómunkát: {exc}")
                else:
                    st.caption("Az utómunka adminisztratívan lezárult; ez önmagában nem minősíti át megfelelőre a karosszériát.")

    with st.expander("MQTT- és feldolgozási hibák", expanded=False):
        if errors.empty:
            st.success("Nincs naplózott üzenetfeldolgozási hiba.")
        else:
            st.dataframe(errors[["received_at", "category", "detail", "raw_payload"]],
                         use_container_width=True, hide_index=True, height=220)
    with st.expander("Utómunka-eseménynapló", expanded=False):
        if actions.empty:
            st.info("Még nincs utómunka-művelet.")
        else:
            st.dataframe(actions[["timestamp", "body_id", "action", "note"]],
                         use_container_width=True, hide_index=True, height=180)

    st.caption("Adatút: szimulátor/UI → MQTT publisher → Mosquitto → monitor és ellenőrző → SQLite → élő dashboard.")
    st.caption("A felület 2 másodpercenként frissül; az MQTT üzenetfeldolgozás külön monitorfolyamatban történik.")


live_monitor_panel()
