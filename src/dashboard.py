"""Live Streamlit dashboard: Excel-backed side-wall recipes, weld checks, and rework queue."""
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

from src.catalog import CatalogError, get_configuration, list_configurations
from src.monitor import (
    BROKER_HOST, BROKER_PORT, DB_PATH, REWORK_DONE,
    REWORK_IN_PROGRESS, REWORK_WAITING, TOPIC,
)
from src.simulator import generate_body_events, publish_events

st.set_page_config(page_title="Oldalfal-hegesztés | Ipar 4.0", page_icon="🏭", layout="wide")
st.title("Autóipari oldalfal-ponthegesztés felügyelete")
st.caption("Élő szimulált gyártócella · Excel-alapú modellkonfigurációk · MQTT-adatút · automatikus utómunka")

try:
    CATALOG = list_configurations()
except CatalogError as exc:
    st.error(f"Nem tölthető be a GitHub-repó Excel-katalógusa: {exc}")
    st.stop()

CONFIG_BY_ID = {config["config_id"]: config for config in CATALOG}
st.warning(
    "Oktatási szimuláció: az Excel-katalógus pontjai és paraméterhatárai szintetikus példák, "
    "nem valódi Audi/CUPRA/VW/Škoda gyártási specifikációk. A mért paraméterek nem igazolják a fizikai kötés szilárdságát."
)


def publish_control_event(event: dict[str, Any]) -> None:
    """Send operator actions via MQTT so the monitor owns the state transitions."""
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
        events = pd.read_sql_query("SELECT * FROM weld_events ORDER BY id DESC LIMIT 1500", conn)
        rework = pd.read_sql_query("SELECT * FROM rework_queue ORDER BY created_at DESC", conn)
        errors = pd.read_sql_query("SELECT * FROM system_errors ORDER BY id DESC LIMIT 100", conn)
        actions = pd.read_sql_query("SELECT * FROM rework_actions ORDER BY id DESC LIMIT 100", conn)
    return bodies, events, rework, errors, actions


def json_list(value: Any) -> list[str]:
    try:
        result = json.loads(value or "[]")
        return [str(x) for x in result] if isinstance(result, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


with st.sidebar:
    st.header("Gyártási konfiguráció")
    options = {cfg["config_id"]: cfg["label"] for cfg in CATALOG}
    selected_config_id = st.selectbox(
        "Járműmodell és alkatrész",
        options=list(options),
        format_func=lambda value: options[value],
    )
    selected_config = CONFIG_BY_ID[selected_config_id]
    limits = selected_config["limits"]
    st.caption(f"Excel-konfiguráció: {selected_config_id}")
    st.metric("Elvárt hegesztési pontok", selected_config["expected_count"])
    st.markdown("**Excelből olvasott határértékek**")
    st.write(f"Áramerősség: {limits.current_min:g}–{limits.current_max:g} kA")
    st.write(f"Hegesztési idő: {limits.weld_time_min:g}–{limits.weld_time_max:g} ms")
    st.write(f"Elektródaerő: {limits.force_min:g}–{limits.force_max:g} kN")
    fault_rate = st.slider("Hibák valószínűsége", 0.0, 0.30, 0.06, 0.01)
    delay_ms = st.slider("Üzenetek közötti késleltetés (ms)", 0, 50, 5, 1)
    if st.button("▶ Új oldalfal indítása", type="primary", use_container_width=True):
        try:
            body_id, generated = generate_body_events(selected_config_id, fault_rate)
            with st.spinner(f"{body_id} üzeneteinek küldése MQTT-n..."):
                publish_events(generated, delay_ms=delay_ms)
            st.session_state["last_body_id"] = body_id
            st.success(f"Indítva: {body_id}")
        except Exception as exc:
            st.error(f"Nem sikerült elindítani a szimulációt: {exc}")
    st.divider()
    st.caption(
        "A modell/oldalfal pontlistáját és a névleges paramétereket a GitHubon verziózott "
        "config/welding_catalog.xlsx adja. Az SQLite csak méréseket, állapotokat, hibákat és utómunka-naplót tárol."
    )
    st.caption("Az Excel módosítása után indítsd újra az alkalmazást a katalógus újraolvasásához.")


@st.fragment(run_every="2s")
def live_monitor_panel() -> None:
    try:
        bodies, events, rework, errors, actions = read_tables()
    except (sqlite3.Error, pd.errors.DatabaseError) as exc:
        st.error(f"Az adatbázis nem olvasható. Ellenőrizd, hogy fut-e a monitor: {exc}")
        return

    if bodies.empty:
        st.info("Várakozás az első oldalfalra. Indítsd el a brokert és a monitort, majd válassz modellt.")
        return

    in_progress = bodies[bodies["status"] == "FOLYAMATBAN"]
    current = in_progress.iloc[0] if not in_progress.empty else bodies.iloc[0]
    body_id = str(current["body_id"])
    config_id = str(current.get("config_id") or "")
    try:
        config = get_configuration(config_id)
        expected_ids = list(config["expected_weld_ids"])
    except CatalogError:
        config = None
        expected_ids = json_list(current.get("expected_ids_json", "[]"))

    body_events = events[events["body_id"] == body_id].copy() if not events.empty else pd.DataFrame()
    if not body_events.empty:
        body_events = body_events.sort_values("id")
    counts = body_events["weld_id"].astype(str).value_counts().to_dict() if not body_events.empty else {}
    seen_expected = len(set(counts).intersection(expected_ids))
    expected_count = len(expected_ids) if expected_ids else int(current.get("expected_count", 0) or 0)
    progress = min(seen_expected / expected_count, 1.0) if expected_count else 0.0
    is_active = str(current["status"]) == "FOLYAMATBAN"

    st.subheader("Aktuális oldalfal a gyártócella végén")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Oldalfal azonosító", body_id)
    c2.metric("Járműmodell", f"{config['brand']} {config['model']}" if config else str(current["body_type"]))
    c3.metric("Alkatrész", config["part"] if config else "Nem elérhető")
    c4.metric("Elvárt pontok", f"{seen_expected} / {expected_count}")
    c5.metric("Paraméterhibák", int(current.get("parameter_errors", 0) or 0))
    st.progress(progress, text=f"Pontteljesség: {progress:.0%} · {'HEGESZTÉS FOLYAMATBAN' if is_active else str(current['status'])}")
    if is_active:
        st.info("A karosszéria-oldalfal feldolgozás alatt áll; a ponttérkép és a mérések frissülnek.")
    elif str(current["status"]) == "MEGFELELŐ":
        st.success("Az oldalfal megfelelt a szimulált ellenőrzésnek.")
    else:
        st.error("SELEJT: az oldalfal automatikusan bekerült az utómunka-sorba.")

    st.markdown("**Legutóbb beérkezett hegesztési mérés**")
    latest = body_events.iloc[-1] if not body_events.empty else None
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

    # One record per Excel-defined spot weld, plus any unexpected incoming IDs.
    point_records: list[dict[str, Any]] = []
    for point in (config["points"] if config else [{"weld_id": wid, "name": wid, "order": idx} for idx, wid in enumerate(expected_ids)]):
        weld_id = point["weld_id"]
        matching = body_events[body_events["weld_id"].astype(str) == weld_id] if not body_events.empty else pd.DataFrame()
        count = len(matching)
        newest = matching.iloc[-1] if count else None
        point_errors = json_list(newest["errors_json"]) if newest is not None else []
        if count == 0:
            point_status, marker = ("FOLYAMATBAN", "⏳") if is_active else ("HIÁNYZIK", "❌")
        elif count > 1 or (newest is not None and bool(newest["duplicate"])):
            point_status, marker = "DUPLIKÁLT", "⚠️"
        elif point_errors:
            point_status, marker = "PARAMÉTERHIBA", "❌"
        else:
            point_status, marker = "MEGFELELŐ", "✅"
        point_records.append({
            "Pont": weld_id, "Megnevezés": point.get("name", weld_id),
            "Állapot": point_status, "Üzenetek": count,
            "Áramerősség (kA)": newest["current_ka"] if newest is not None else None,
            "Hegesztési idő (ms)": newest["weld_time_ms"] if newest is not None else None,
            "Elektródaerő (kN)": newest["electrode_force_kn"] if newest is not None else None,
            "Hiba / megjegyzés": "; ".join(point_errors),
            "_map_label": f"{marker} {weld_id}",
        })

    expected_set = set(expected_ids)
    for weld_id in sorted(set(counts) - expected_set):
        matching = body_events[body_events["weld_id"].astype(str) == weld_id]
        newest = matching.iloc[-1]
        point_records.append({
            "Pont": weld_id, "Megnevezés": "Váratlan pontazonosító",
            "Állapot": "VÁRATLAN PONT", "Üzenetek": len(matching),
            "Áramerősség (kA)": newest["current_ka"], "Hegesztési idő (ms)": newest["weld_time_ms"],
            "Elektródaerő (kN)": newest["electrode_force_kn"],
            "Hiba / megjegyzés": "Nem szerepel az Excel-katalógus elvárt pontlistájában.",
            "_map_label": f"⚠️ {weld_id}",
        })

    st.markdown("**Oldalfal hegesztési ponttérképe** — ✅ rendben · ⏳ még nem érkezett meg · ❌ hiányzó/paraméterhiba · ⚠️ duplikált/váratlan")
    labels = [row["_map_label"] for row in point_records]
    if labels:
        width = 8
        grid_rows = [labels[i:i + width] for i in range(0, len(labels), width)]
        grid_df = pd.DataFrame([row + [""] * (width - len(row)) for row in grid_rows],
                               columns=[f"Pontcsoport {i + 1}" for i in range(width)])
        st.dataframe(grid_df, use_container_width=True, hide_index=True, height=min(430, 36 * (len(grid_rows) + 1)))
    with st.expander("Az oldalfal összes hegesztési pontjának paraméterei", expanded=False):
        if point_records:
            st.dataframe(pd.DataFrame(point_records).drop(columns=["_map_label"]),
                         use_container_width=True, hide_index=True, height=380)

    st.subheader("Oldalfalak ellenőrzési előzményei")
    history = bodies.copy()
    for source, label in [
        ("missing_ids_json", "Hiányzó pontok"),
        ("unexpected_ids_json", "Váratlan pontok"),
        ("duplicate_ids_json", "Duplikált pontok"),
    ]:
        history[label] = history[source].apply(lambda x: ", ".join(json_list(x)))
    hist_cols = ["body_id", "config_id", "body_type", "expected_count", "event_count", "status",
                 "parameter_errors", "latency_ms", "Hiányzó pontok", "Váratlan pontok",
                 "Duplikált pontok", "started_at", "completed_at"]
    st.dataframe(history[hist_cols], use_container_width=True, hide_index=True, height=230)

    st.subheader("Automatikus utómunka-sor")
    if rework.empty:
        st.success("Jelenleg nincs selejtes oldalfal az utómunka-soron.")
    else:
        active_rework = rework[rework["status"] != REWORK_DONE]
        a, b, c = st.columns(3)
        a.metric("Összes utómunka-eset", len(rework))
        b.metric("Nyitott esetek", len(active_rework))
        c.metric("Utómunka adminisztratívan lezárva", int((rework["status"] == REWORK_DONE).sum()))
        st.dataframe(rework[["body_id", "reason", "status", "created_at", "updated_at", "resolution_note"]],
                     use_container_width=True, hide_index=True)
        for _, item in rework.iterrows():
            queue_id = str(item["body_id"])
            with st.expander(f"{queue_id} — {item['status']}"):
                st.write("**Hiba oka:** " + str(item["reason"]))
                note = st.text_input("Utómunka megjegyzése", key=f"note_{queue_id}")
                if item["status"] == REWORK_WAITING:
                    if st.button("Utómunka megkezdése", key=f"start_{queue_id}"):
                        try:
                            publish_control_event({"event_type": "rework_action", "body_id": queue_id,
                                "action": "START", "note": note, "timestamp": pd.Timestamp.now(tz="UTC").isoformat()})
                            st.toast("Az utómunka megkezdését MQTT-n elküldtem.")
                        except Exception as exc:
                            st.error(f"Nem sikerült rögzíteni az utómunkát: {exc}")
                elif item["status"] == REWORK_IN_PROGRESS:
                    if st.button("Utómunka kész — újraellenőrzés szükséges", key=f"complete_{queue_id}"):
                        try:
                            publish_control_event({"event_type": "rework_action", "body_id": queue_id,
                                "action": "COMPLETE", "note": note, "timestamp": pd.Timestamp.now(tz="UTC").isoformat()})
                            st.toast("Utómunka lezárva; az oldalfal újraellenőrzésre vár.")
                        except Exception as exc:
                            st.error(f"Nem sikerült lezárni az utómunkát: {exc}")
                else:
                    st.caption("Az utómunka adminisztratívan lezárult, de az eredeti selejtes minősítés megmarad.")

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

    st.caption("Adatút: XLSX referenciakatalógus → szimulátor → MQTT/Mosquitto → monitor és ellenőrző → SQLite futásnapló → élő dashboard.")
    st.caption("A felület 2 másodpercenként frissül; az adatbázis nem helyettesíti az Excel referencia-konfigurációt.")


live_monitor_panel()
