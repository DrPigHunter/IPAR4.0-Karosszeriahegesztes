"""Literature-informed plausibility screening for the synthetic catalog recipes.

This is a screening aid, not a welding-procedure qualification or weld-strength test.
The broad envelope deliberately does not pretend to replace a material/joint-specific
weld-lobe study or an OEM welding schedule.
"""
from __future__ import annotations

from typing import Any, Iterable

# Broad reference values used only for screening coated automotive-steel examples.
# EAA notes steel spot welding is usually possible below 15 kA and 0.2–4 kN;
# a peer-reviewed 22MnB5+AS150 study used 2.0–6.0 kN and found a 4.6–6.0 kA
# range for its specific 1.5 mm joint. The widened force envelope is deliberate.
STEEL_REFERENCE_CURRENT_MAX_KA = 15.0
STEEL_REFERENCE_FORCE_MIN_KN = 0.2
STEEL_REFERENCE_FORCE_MAX_KN = 6.0


# A katalógusértékeket szakmai referencia-tartományokhoz hasonlítom egy előzetes hihetőségi szűrésben; ez nem hegesztési eljárásminősítés.
def build_parameter_audit(configurations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return catalog measurements plus transparent, broad plausibility-screen findings."""
    rows: list[dict[str, Any]] = []
    for config in configurations:
        limits = config["limits"]
        points = list(config.get("points", []))
        currents = [float(p["nominal_current_ka"]) for p in points]
        times = [float(p["nominal_weld_time_ms"]) for p in points]
        forces = [float(p["nominal_electrode_force_kn"]) for p in points]
        findings: list[str] = []

        if float(limits.current_min) <= 0.0 or float(limits.current_max) <= 0.0:
            findings.append("Az áramhatárértéknek pozitívnak kell lennie.")
        if float(limits.current_max) > STEEL_REFERENCE_CURRENT_MAX_KA:
            findings.append(
                f"A maximális áram meghaladja a {STEEL_REFERENCE_CURRENT_MAX_KA:.1f} kA-os "
                "általános acél-referenciaértéket; konkrét recept szerinti igazolás szükséges."
            )
        if float(limits.force_min) < STEEL_REFERENCE_FORCE_MIN_KN:
            findings.append(
                f"Az elektródaerő alsó határa {STEEL_REFERENCE_FORCE_MIN_KN:.1f} kN alatt van; "
                "ellenőrizd a pisztoly és az illesztés sajátosságait."
            )
        if float(limits.force_max) > STEEL_REFERENCE_FORCE_MAX_KN:
            findings.append(
                f"Az elektródaerő felső határa {STEEL_REFERENCE_FORCE_MAX_KN:.1f} kN felett van; "
                "konkrét pisztoly-/anyag-referencia szükséges."
            )
        if any(value <= 0.0 for value in times):
            findings.append("Nem pozitív hegesztési idő szerepel a katalógusban.")
        if any(value <= 0.0 for value in currents):
            findings.append("Nem pozitív névleges áram szerepel a katalógusban.")
        if any(value <= 0.0 for value in forces):
            findings.append("Nem pozitív névleges elektródaerő szerepel a katalógusban.")
        if not points:
            findings.append("A modellhez nem tartozik pontrecept.")

        rows.append({
            "Konfiguráció": str(config.get("config_id", "")),
            "Modell / alkatrész": str(config.get("label", config.get("body_type", ""))),
            "Pontok száma": len(points),
            "Áramhatár min (kA)": float(limits.current_min),
            "Áramhatár max (kA)": float(limits.current_max),
            "Névleges áram min (kA)": min(currents) if currents else None,
            "Névleges áram max (kA)": max(currents) if currents else None,
            "Időhatár min (ms)": float(limits.weld_time_min),
            "Időhatár max (ms)": float(limits.weld_time_max),
            "Névleges idő min (ms)": min(times) if times else None,
            "Névleges idő max (ms)": max(times) if times else None,
            "Erőhatár min (kN)": float(limits.force_min),
            "Erőhatár max (kN)": float(limits.force_max),
            "Névleges erő min (kN)": min(forces) if forces else None,
            "Névleges erő max (kN)": max(forces) if forces else None,
            "Referencia-ellenőrzés": "FELÜLVIZSGÁLAT" if findings else "PLAUZIBILIS, NEM IGAZOLT",
            "Megjegyzések": " ".join(findings) if findings else (
                "Az egyszerű referencia-szűrőn megfelelt. Ez nem bizonyítja, hogy a recept az adott "
                "anyaghoz, lemezvastagsághoz, bevonathoz vagy pisztolyhoz megfelelő."
            ),
        })
    return rows
