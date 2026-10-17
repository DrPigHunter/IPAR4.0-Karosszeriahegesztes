# Autóipari karosszéria-ponthegesztési folyamat szimulációja MQTT-alapú adatközvetítéssel

Szoftveres Ipar 4.0 demonstráció: karosszériák és hegesztési pontok szimulációja, MQTT-alapú adatküldés, élő paraméterellenőrzés és automatikus selejt/utómunka-kezelés.

> Oktatási szimuláció. A generált adatok nem valódi gyártási mérések, és a program nem bizonyítja egy fizikai hegesztési kötés tényleges minőségét.

## Funkciók

- Karosszériatípusok és az elvárt hegesztési pontok listája már a folyamat elején rendelkezésre áll.
- Szimulált áramerősség, hegesztési idő és elektródaerő.
- Szándékos hibák: hiányzó pont, határértéken kívüli paraméter, duplikált üzenet és váratlan pontazonosító.
- MQTT publisher, Mosquitto broker és külön subscriber/ellenőrző.
- Duplikált üzenetek külön eseményként maradnak meg; a hiányzó pontokat a karosszéria lezárásakor ellenőrzi.
- A nem megfelelő karosszéria automatikusan bekerül az utómunka-sorba.
- Az utómunka állapota és kezelői megjegyzései is rögzülnek MQTT-n és SQLite-ban.
- 2 másodpercenként frissülő Streamlit dashboard élő karosszéria-állapottal, ponttérképpel, mért paraméterekkel, eseménytörténettel, hibajegyzékkel és utómunka-listával.

## Követelmények

- Python 3.11 vagy újabb
- Docker Desktop (a Mosquitto MQTT-broker futtatásához)

## Indítás Windows alatt

PowerShellben, a projekt gyökérmappájában:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
docker compose up -d mqtt
```

Egy külön PowerShell ablakban indítsd el az adatfogadót és ellenőrzőt:

```powershell
.\.venv\Scripts\Activate.ps1
python -m src.monitor
```

Egy másik ablakban indítsd el a kezelőfelületet:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run src/dashboard.py
```

A böngészőben elérhető dashboardon indíts egy karosszériát. A ponttérkép és a legutóbbi hegesztési paraméterek automatikusan frissülnek. Ha egy karosszéria bármely ellenőrzésen elbukik, a monitor automatikusan selejtnek jelöli és az utómunka-sorba teszi. A dashboardon az utómunka elindítható és lezárható; a lezárás újraellenőrzést igényel, nem állítja automatikusan megfelelőre a karosszériát.

A szimulátor parancssorból is futtatható:

```powershell
python -m src.simulator --body-type Sedan --fault-rate 0.05
```

## Adatút

`Szimulátor / dashboard → MQTT (Mosquitto) → monitor és ellenőrző → SQLite → élő dashboard`

A kezelői utómunka-műveletek szintén a `welding/events` MQTT-témán mennek keresztül.

## Ellenőrzési szabályok

- Az elvárt összes hegesztési pontnak meg kell jelennie.
- Az áramerősségnek, hegesztési időnek és elektródaerőnek a konfigurált határokon belül kell lennie.
- A duplikált és váratlan pontazonosítók hibának minősülnek.
- Hibás vagy nem támogatott MQTT-esemény esetén hibabejegyzés jelenik meg a dashboardon.
- A nem megfelelő karosszériák automatikusan az utómunka-sorba kerülnek.
- Utómunka lezárásakor újraellenőrzés szükséges, az eredeti selejtes minősítés nem törlődik automatikusan.

A küszöbértékek demonstrációs célú, szimulált értékek, nem Audi-specifikációk.

## Tesztek

```powershell
python -m unittest discover -s tests -v
```

A tesztek a paraméterhatárokat, a hiányzó és duplikált pontokat, a selejt utómunka-sorba helyezését és az utómunka állapotátmeneteit ellenőrzik.

## Fontos korlát

A rendszer szimulált folyamatadatokat és üzenetek teljességét ellenőrzi. Valódi hegesztési kötés fizikai minőségének megállapítására önmagában nem alkalmas.
