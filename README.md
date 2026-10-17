# Autóipari karosszéria-ponthegesztési folyamat szimulációja MQTT-alapú adatközvetítéssel

Szoftveres Ipar 4.0 demonstráció: karosszériák és hegesztési pontok szimulációja, MQTT-alapú adatküldés, folyamatparaméter-ellenőrzés és selejtjelzés.

> Oktatási célú szimuláció. A generált adatok nem valódi gyártási mérések, és a program nem bizonyítja egy fizikai hegesztési kötés tényleges minőségét.

## Funkciók

- Több karosszériatípus, típusonként konfigurált hegesztési pontokkal.
- Szimulált áramerősség, hegesztési idő és elektródaerő.
- Szándékosan előidézhető hiányzó, határértéken kívüli és duplikált üzenetek.
- MQTT publisher, Mosquitto broker és külön subscriber/ellenőrző.
- SQLite-alapú eredménytárolás és Streamlit kezelőfelület.
- Tesztelhető hibafelismerés és késleltetésmérés.

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

A böngészőben megnyíló felületen válaszd ki a karosszériatípust, állítsd be a hibák valószínűségét, majd indítsd el a szimulációt. A dashboard MQTT-n publikálja az eseményeket; a külön monitor dolgozza fel és menti őket.

A szimulátor parancssorból is futtatható:

```powershell
python -m src.simulator --body-type Sedan --fault-rate 0.05
```

## Architekturális adatút

`Szimulátor / dashboard publisher -> MQTT (Mosquitto) -> monitor és ellenőrző -> SQLite -> Streamlit dashboard`

## Ellenőrzési szabályok

- A karosszériatípushoz tartozó összes elvárt hegesztési pontnak meg kell jelennie.
- Az áramerősségnek, hegesztési időnek és elektródaerőnek a konfigurált határokon belül kell lennie.
- A duplikált hegesztésipont-üzeneteket külön jelöli a rendszer.
- Ha hiányzó pont vagy paraméterhiba van, a karosszéria állapota `SELEJT / ELLENŐRIZENDŐ` lesz.

A küszöbértékek demonstrációs célú, szimulált értékek, nem Audi-specifikációk.

## Tesztek

```powershell
python -m unittest discover -s tests -v
```

A tesztek a pontteljességet, a paraméterhatárokat, a duplikációkat és a karosszériaállapot meghatározását vizsgálják.

## Fontos korlát

A rendszer a szimulált folyamatadatokat és üzenetek teljességét ellenőrzi. Valódi hegesztési kötés fizikai minőségének megállapítására önmagában nem alkalmas.
