# BODYLINE — Autóipari oldalfal-ponthegesztési szimuláció

Ipar 4.0 oktatási demonstráció: tíz járműmodell bal oldalfalának ponthegesztése, MQTT-alapú adatközvetítéssel, pont- és paraméterellenőrzéssel, élő felügyelettel és utómunka-nyilvántartással.

> **Fontos:** a katalógus és minden folyamatparaméter szintetikus, demonstrációs adat. Nem valós Audi/CUPRA/Volkswagen/Škoda gyártási specifikáció, és a szoftveres ellenőrzés nem bizonyítja a fizikai hegesztési kötés szilárdságát.

## Gyors indítás Windows alatt

**Előfeltételek:** Python 3.11 vagy újabb, Docker Desktop WSL 2 támogatással, engedélyezett Virtual Machine Platform.

1. Indítsd el a Docker Desktopot, és várd meg, amíg a Docker Engine készen áll.
2. A projekt gyökérmappájában futtasd a **Start_HegesztesSzimulacio.ps1** scriptet:
   - PowerShellből: .\Start_HegesztesSzimulacio.ps1
   - Ha a Windows letiltja a script futtatását, csak az aktuális PowerShell-ablakra engedélyezheted: Set-ExecutionPolicy -Scope Process Bypass, majd futtasd újra a scriptet.
3. A script létrehozza a virtuális környezetet, telepíti a Python-csomagokat, elindítja az MQTT-brokert, külön terminálban megnyitja a monitort és a webes felületet, majd megnyitja a böngészőt.

A webes felület címe: **http://localhost:8501**

A monitor és a dashboard két külön PowerShell-ablakban fut; hagyd nyitva ezeket a szimuláció közben. Az **Élő gyártás** fülön az automatikus gyártás alapértelmezetten elindul. Egy oldalfal hegesztése 90 ms-os pontközzel szimulálódik, és a ciklus célideje 20 másodperc alatt van. Egy ciklus befejezése után a rendszer 10 másodpercet vár, majd automatikusan másik modellt választ. Az automatika a webes felületen leállítható és újraindítható.

## Kézi indítás

A projekt gyökérmappájában:

    py -3 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    docker compose up -d mqtt

Egy másik PowerShell-ablakban:

    .\.venv\Scripts\Activate.ps1
    python -m src.monitor

Egy harmadik ablakban:

    .\.venv\Scripts\Activate.ps1
    streamlit run src/dashboard.py

## Kétfüles felület

- **Élő gyártás:** kompakt állapotjelzők, aktuális karosszéria, pontteljesség és színkódolt ponttérkép görgethető, hosszú mérési táblázat nélkül.
- **Statisztika és utómunka:** megfelelési/selejtarány, modellenkénti eredmények, karosszéria-előzmények, mérési napló, hibanapló és utómunka-kezelés.
- **Automatizálás:** a 10 modellből a rendszer automatikusan választ; új karosszériát 5 másodperces indítási időközzel küld a szimulációba.
- **Hibavalószínűség:** alapértelmezetten 0 (nincs automatikusan injektált hiba). A statisztika fülön demonstrációs hibateszthez állítható.
- **Utómunka:** a hiányzó pont, határértéken kívüli paraméter, duplikált vagy váratlan pont továbbra is hibának számít, és automatikusan utómunka-sorba kerül.

## Excel-katalógus

A config/welding_catalog.xlsx az alkalmazás referencia-konfigurációja, két munkalappal:

- **Modellek:** konfigurációk, elvárt pontszámok és modellfüggő szintetikus határértékek.
- **Hegesztési pontok:** minden ponthoz egyedi azonosító, sorrend, megnevezés és szimulált névleges paraméterek.

| Járműmodell | Bal oldalfal hegesztési pontjai |
|---|---:|
| CUPRA Terramar | 118 |
| Audi Q8 | 124 |
| Audi Q5 | 130 |
| Audi Q3 | 136 |
| Audi Q4 e-tron | 142 |
| Audi A6 | 115 |
| Audi A3 | 121 |
| Volkswagen Tiguan | 127 |
| Volkswagen ID.4 | 133 |
| Škoda Kodiaq | 139 |

Minden modellen 100–150 közötti hegesztési pont szerepel. A tools/generate_catalog.py reprodukálhatóan újra tudja készíteni a munkafüzetet; a GitHub Actions a generátor módosításakor frissíti a verziózott XLSX-et.

Az SQLite kizárólag futási adatokat tárol: mérési eseményeket, karosszériaállapotokat, feldolgozási hibákat és utómunka-naplót. Nem helyettesíti az Excel-referenciakatalógust.

## Automatikus futásnaplók

Minden lezárt karosszériaciklusról a monitor külön JSON-fájlt ment a `logs` mappába. A jelentés tartalmazza a modellt, a várt és beérkezett pontokat, a teljességi arányt, a paraméterhibákat, a minősítést, az utómunkát és a mért ciklusidőt. Emellett a rendszer napi `production_ÉÉÉÉ-HH-NN.jsonl` eseménynaplót és `production_summary.json` összesítőt frissít. Ezek a generált naplók helyi fájlok, a Git nem követi őket.

Az összesítő adatbázisból számol, így tartalmazhat korábbi verziókból származó futásokat is. A dashboard fő statisztikái az aktuális böngésző-munkamenet új ciklusait külön számolják, a korábbi futások pedig az előzményekben maradnak.

## Tesztek futtatása

    python -m unittest discover -s tests -v

A tesztek ellenőrzik a katalógus szerkezetét és pontszámait, a szimulátor eseménysorát, a paraméterhatárokat, a hiányzó és duplikált pontokat, valamint az automatikus utómunka-kezelést.
