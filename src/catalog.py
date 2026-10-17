"""Load the version-controlled XLSX welding catalogue (never from the runtime DB)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from src.rules import Limits

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "welding_catalog.xlsx"


class CatalogError(RuntimeError):
    """The reference workbook is missing, incomplete, or inconsistent."""


def _as_float(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise CatalogError(f"Hiányzó vagy hibás Excel-beállítás: {key}={value!r}") from exc


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, dict[str, Any]]:
    """Load all model/part configurations and weld-point recipes from the tracked Excel file."""
    if not CATALOG_PATH.exists():
        raise CatalogError(
            f"Nem található a konfigurációs Excel: {CATALOG_PATH}. "
            "Ellenőrizd, hogy a config/welding_catalog.xlsx fájlt letöltötted-e a GitHub-repóból."
        )

    workbook = load_workbook(CATALOG_PATH, read_only=True, data_only=True)
    required_sheets = {"Modellek", "Hegesztési pontok"}
    if not required_sheets.issubset(set(workbook.sheetnames)):
        raise CatalogError(f"Hiányzó munkalap az Excelben. Szükséges: {sorted(required_sheets)}")

    def read_rows(sheet_name: str) -> list[dict[str, Any]]:
        ws = workbook[sheet_name]
        iterator = ws.iter_rows(values_only=True)
        headers = next(iterator, None)
        if not headers:
            return []
        names = [str(v).strip() if v is not None else "" for v in headers]
        return [
            {name: value for name, value in zip(names, values) if name}
            for values in iterator
            if any(value is not None for value in values)
        ]

    config_rows = read_rows("Modellek")
    point_rows = read_rows("Hegesztési pontok")
    workbook.close()

    if not config_rows or not point_rows:
        raise CatalogError("Az Excel konfigurációs vagy hegesztési pont munkalapja üres.")

    result: dict[str, dict[str, Any]] = {}
    for row in config_rows:
        config_id = str(row.get("config_id") or "").strip()
        if not config_id or config_id in result:
            raise CatalogError(f"Hiányzó vagy duplikált config_id a Modellek munkalapon: {config_id!r}")
        brand, model, part = (str(row.get(k) or "").strip() for k in ("Gyártó", "Modell", "Alkatrész"))
        if not brand or not model or not part:
            raise CatalogError(f"Hiányos gyártó/modell/alkatrész konfiguráció: {config_id}")
        result[config_id] = {
            "config_id": config_id, "brand": brand, "model": model, "part": part,
            "label": f"{brand} {model} — {part}",
            "expected_count": int(_as_float(row, "Elvárt pontok száma")),
            "limits": Limits(
                current_min=_as_float(row, "Áramerősség min (kA)"),
                current_max=_as_float(row, "Áramerősség max (kA)"),
                weld_time_min=_as_float(row, "Hegesztési idő min (ms)"),
                weld_time_max=_as_float(row, "Hegesztési idő max (ms)"),
                force_min=_as_float(row, "Elektródaerő min (kN)"),
                force_max=_as_float(row, "Elektródaerő max (kN)"),
            ),
            "points": [],
        }

    for row in point_rows:
        config_id = str(row.get("config_id") or "").strip()
        if config_id not in result:
            raise CatalogError(f"A Hegesztési pontok lapon ismeretlen config_id: {config_id!r}")
        weld_id = str(row.get("weld_id") or "").strip()
        if not weld_id:
            raise CatalogError(f"Hiányzó weld_id ehhez a konfigurációhoz: {config_id}")
        config = result[config_id]
        config["points"].append({
            "weld_id": weld_id,
            "name": str(row.get("Pont megnevezése") or weld_id),
            "order": int(_as_float(row, "Sorrend")),
            "nominal_current_ka": _as_float(row, "Névleges áramerősség (kA)"),
            "nominal_weld_time_ms": _as_float(row, "Névleges hegesztési idő (ms)"),
            "nominal_electrode_force_kn": _as_float(row, "Névleges elektródaerő (kN)"),
        })

    for config_id, config in result.items():
        config["points"].sort(key=lambda item: item["order"])
        ids = [p["weld_id"] for p in config["points"]]
        if len(ids) != len(set(ids)):
            raise CatalogError(f"Duplikált hegesztési pontazonosító a konfigurációban: {config_id}")
        if len(ids) != config["expected_count"]:
            raise CatalogError(
                f"{config_id}: Excel szerint {config['expected_count']} pont kell, "
                f"de a Hegesztési pontok lapon {len(ids)} szerepel."
            )
        limits: Limits = config["limits"]
        for point in config["points"]:
            for key, low, high in (
                ("nominal_current_ka", limits.current_min, limits.current_max),
                ("nominal_weld_time_ms", limits.weld_time_min, limits.weld_time_max),
                ("nominal_electrode_force_kn", limits.force_min, limits.force_max),
            ):
                if not low <= point[key] <= high:
                    raise CatalogError(
                        f"{config_id}/{point['weld_id']}: {key} névleges értéke "
                        f"kívül esik a Modellek munkalapon megadott határokon."
                    )
        config["expected_weld_ids"] = ids

    return result


def list_configurations() -> list[dict[str, Any]]:
    """Return catalog configurations sorted for the UI."""
    return sorted(load_catalog().values(), key=lambda cfg: (cfg["brand"], cfg["model"], cfg["part"]))


def get_configuration(config_id: str) -> dict[str, Any]:
    """Return one Excel-defined model/part configuration or raise a readable error."""
    try:
        return load_catalog()[config_id]
    except KeyError as exc:
        raise CatalogError(f"Ismeretlen konfiguráció: {config_id!r}. Ellenőrizd a GitHubon lévő Excel katalógust.") from exc


def reload_catalog() -> None:
    """Clear in-process cache after the reference workbook has been replaced."""
    load_catalog.cache_clear()
