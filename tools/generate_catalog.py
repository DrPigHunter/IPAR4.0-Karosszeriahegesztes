#!/usr/bin/env python3
"""Generate the versioned, synthetic 100–150 spot-weld Excel catalogue."""
from __future__ import annotations

import random
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config" / "welding_catalog.xlsx"

# Counts and process limits are deliberately synthetic educational values—not OEM specs.
MODELS = [
    ("CUPRA", "Terramar", "CT", 118, 7.00, 10.40, 155, 335, 2.60, 4.20),
    ("Audi", "Q8", "Q8", 124, 7.10, 10.60, 160, 340, 2.70, 4.30),
    ("Audi", "Q5", "Q5", 130, 7.20, 10.50, 158, 338, 2.60, 4.40),
    ("Audi", "Q3", "Q3", 136, 7.00, 10.30, 152, 332, 2.50, 4.10),
    ("Audi", "Q4 e-tron", "Q4", 142, 7.30, 10.80, 162, 342, 2.80, 4.40),
    ("Audi", "A6", "A6", 115, 7.40, 10.70, 165, 345, 2.90, 4.50),
    ("Audi", "A3", "A3", 121, 7.10, 10.20, 154, 330, 2.50, 4.00),
    ("Volkswagen", "Tiguan", "TG", 127, 7.20, 10.60, 159, 339, 2.60, 4.30),
    ("Volkswagen", "ID.4", "ID4", 133, 7.30, 10.90, 161, 344, 2.70, 4.50),
    ("Škoda", "Kodiaq", "KD", 139, 7.00, 10.40, 156, 336, 2.50, 4.20),
]

MODEL_HEADERS = [
    "config_id", "Gyártó", "Modell", "Alkatrész", "Elvárt pontok száma",
    "Áramerősség min (kA)", "Áramerősség max (kA)",
    "Hegesztési idő min (ms)", "Hegesztési idő max (ms)",
    "Elektródaerő min (kN)", "Elektródaerő max (kN)",
]
POINT_HEADERS = [
    "config_id", "weld_id", "Pont megnevezése", "Sorrend",
    "Névleges áramerősség (kA)", "Névleges hegesztési idő (ms)",
    "Névleges elektródaerő (kN)",
]


def style_sheet(ws) -> None:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    for column_cells in ws.columns:
        letter = get_column_letter(column_cells[0].column)
        max_len = max(len(str(cell.value or "")) for cell in column_cells)
        ws.column_dimensions[letter].width = min(max(max_len + 2, 14), 34)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    models_ws = wb.active
    models_ws.title = "Modellek"
    points_ws = wb.create_sheet("Hegesztési pontok")
    models_ws.append(MODEL_HEADERS)
    points_ws.append(POINT_HEADERS)

    for brand, model, prefix, count, cmin, cmax, tmin, tmax, fmin, fmax in MODELS:
        config_id = f"{prefix}_LEFT_SIDEWALL"
        models_ws.append([
            config_id, brand, model, "Oldalfal (bal)", count,
            cmin, cmax, tmin, tmax, fmin, fmax,
        ])
        rng = random.Random(config_id)
        for order in range(1, count + 1):
            # Keep every nominal value comfortably within this model's own synthetic limits.
            current = round(rng.uniform(cmin + (cmax - cmin) * 0.25,
                                        cmin + (cmax - cmin) * 0.75), 2)
            weld_time = round(rng.uniform(tmin + (tmax - tmin) * 0.25,
                                          tmin + (tmax - tmin) * 0.75), 1)
            force = round(rng.uniform(fmin + (fmax - fmin) * 0.25,
                                      fmin + (fmax - fmin) * 0.75), 2)
            points_ws.append([
                config_id, f"{prefix}-W{order:03d}",
                f"Oldalfal hegesztési pont {order:03d}", order,
                current, weld_time, force,
            ])

    style_sheet(models_ws)
    style_sheet(points_ws)
    wb.properties.title = "Szimulált jármű-oldalfal ponthegesztési katalógus"
    wb.properties.subject = (
        "Oktatási célú, szintetikus adatok; nem valós gyártási paraméterek."
    )
    wb.properties.creator = "Ipar 4.0 demonstráció"
    wb.save(OUTPUT)
    total = sum(row[3] for row in MODELS)
    print(f"Excel-katalógus létrehozva: {OUTPUT}")
    print(f"Modellek: {len(MODELS)}; összes hegesztési pont: {total}; modellenként 115–142 pont.")


if __name__ == "__main__":
    main()
