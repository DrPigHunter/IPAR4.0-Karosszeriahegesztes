"""A BODYLINE mérési csatornáinak és logikai beavatkozási pontjainak leírása.

A csatornák virtuális érzékelők: a szimulátor állítja elő az adatokat, a projekt
nem csatlakozik fizikai áram-, idő- vagy erőmérőhöz.
"""
from __future__ import annotations

from typing import Any


VIRTUAL_SENSOR_CHANNELS = (
    {
        "sensor_id": "VS-CURRENT-01",
        "name": "Hegesztőáram virtuális mérőcsatorna",
        "signal": "current_ka",
        "quantity": "Hegesztőáram",
        "unit": "kA",
        "sampling": "Eseményvezérelt; egy érték minden hegesztési pontnál",
        "origin": "A katalógus névleges értékéből és a szimulált variációból képzett adat",
    },
    {
        "sensor_id": "VS-TIMER-01",
        "name": "Hegesztési idő virtuális időmérő",
        "signal": "weld_time_ms",
        "quantity": "Hegesztési idő",
        "unit": "ms",
        "sampling": "Eseményvezérelt; egy érték minden hegesztési pontnál",
        "origin": "A katalógus névleges értékéből és a szimulált variációból képzett adat",
    },
    {
        "sensor_id": "VS-FORCE-01",
        "name": "Elektródaerő virtuális mérőcsatorna",
        "signal": "electrode_force_kn",
        "quantity": "Elektródaerő",
        "unit": "kN",
        "sampling": "Eseményvezérelt; egy érték minden hegesztési pontnál",
        "origin": "A katalógus névleges értékéből és a szimulált variációból képzett adat",
    },
)


LOGICAL_ACTUATOR_POINTS = (
    {
        "actuator_id": "LA-PARAM-COMP-01",
        "name": "Korlátozott folyamatparaméter-korrekció",
        "output": "Szimulált áram-/hegesztésiidő-módosítás",
        "trigger": "Az elektródakopási minőségi proxy eltér a beállított céltól",
        "physical_output": False,
    },
    {
        "actuator_id": "LA-REWORK-ROUTE-01",
        "name": "Utómunka-útvonal logikai kapcsolója",
        "output": "Hibás oldalfal felvétele az SQLite utómunka-sorába",
        "trigger": "Hiányzó, váratlan, duplikált pont vagy határértéken kívüli adat",
        "physical_output": False,
    },
    {
        "actuator_id": "LA-TOOL-CHANGE-01",
        "name": "Elektródaegység-csere szimulációja",
        "output": "Kopási állapot nullázása és csereesemény naplózása",
        "trigger": "A beállított oldalfalciklus-intervallum elérése",
        "physical_output": False,
    },
)


OPERATOR_INTERACTIONS = (
    {"point": "Gyártás indítása / leállítása", "input": "Dashboard gomb", "effect": "Automatikus ciklus elindítása vagy biztonságos leállítás kérése"},
    {"point": "Szimulációs sebesség", "input": "100–10 000% numerikus beállítás", "effect": "A pontközi és ciklusközi szimulációs várakozás skálázása"},
    {"point": "Utómunka kezelése", "input": "START / COMPLETE művelet és megjegyzés", "effect": "Az utómunka állapotának módosítása és naplózása"},
    {"point": "Eredmények exportálása", "input": "Dashboard export művelet", "effect": "Dátumozott XLSX-riport létrehozása"},
)


def sensor_catalog() -> list[dict[str, Any]]:
    """A dashboardhoz és a dokumentációhoz visszaadja a virtuális mérőcsatornákat."""
    return [dict(item) for item in VIRTUAL_SENSOR_CHANNELS]


def actuator_catalog() -> list[dict[str, Any]]:
    """A szoftveres beavatkozási pontokat adja vissza; ezek nem fizikai aktuátorok."""
    return [dict(item) for item in LOGICAL_ACTUATOR_POINTS]


def operator_interaction_catalog() -> list[dict[str, Any]]:
    """A kezelő és a rendszer közötti interakciós pontokat sorolja fel."""
    return [dict(item) for item in OPERATOR_INTERACTIONS]


def attach_virtual_sensor_metadata(event: dict[str, Any]) -> dict[str, Any]:
    """A hegesztési eredményhez csatolja, melyik virtuális csatornából jött a jel."""
    if event.get("event_type") != "weld_result":
        return event
    event["signal_origin"] = "SIMULATED_VIRTUAL_SENSOR"
    event["sensor_sources"] = {
        item["signal"]: item["sensor_id"] for item in VIRTUAL_SENSOR_CHANNELS
    }
    event["sampling_method"] = "ONE_EVENT_SAMPLE_PER_WELD_POINT"
    return event
