# Autóipari oldalfal-ponthegesztési folyamat szimulációja MQTT-alapú adatközvetítéssel

Szoftveres Ipar 4.0 demonstráció: tíz különböző járműmodell bal oldalfalának hegesztési szimulációja, modellhez rendelt pontlistával és külön paraméterhatárokkal.

> Oktatási szimuláció. A GitHubon tárolt Excel-katalógus minden pontja, névleges értéke és határértéke szintetikus; nem valódi Audi/CUPRA/VW/Škoda gyártási specifikáció.

## Excel a referencia-adatforrás

A `config/welding_catalog.xlsx` a GitHubon tárolt natív Excel-referencia-munkafüzet, két munkalappal. Ez az alkalmazás egyetlen referencia-konfigurációs forrása:

- **Modellek** lap: 10 járműmodell, mindegyikhez külön `config_id`, bal oldalfal, elvárt pontszám és saját áramerősség-, hegesztésiidő- és elektródaerő-határérték.
- **Hegesztési pontok** lap: modellenként eltérő pontazonosítók, pontmegnevezések, sorrend és szimulált névleges paraméterek.
- Az alkalmazás a kiválasztott konfiguráció névleges értékeiből generál adatot, a monitor pedig ugyanannak az Excel-konfigurációnak a határértékeihez méri.
- A `Modellek` és `Hegesztési pontok` külön munkalapon szerepel. Az SQLite nem helyettesíti és nem generálja a konfigurációkat: kizárólag a mérési eseményeket, futási állapotokat, hibákat és az utómunka naplóját tárolja.

Példák a modellekre: CUPRA Terramar, Audi Q8, Q5, Q3, Q4 e-tron, A6, A3, Volkswagen Tiguan, ID.4 és Škoda Kodiaq. Ezekhez a projekt demonstrációs, saját pontazonosítókat és eltérő szintetikus paramétereket használ.

## Funkciók

- Valós időben követhető aktív oldalfal, pontteljességi folyamatjelző és ponttérkép.
- Minden ponthoz áramerősség (kA), hegesztési idő (ms) és elektródaerő (kN).
- Hibaszcenáriók: hiányzó pont, határértéken kívüli paraméter, duplikált üzenet, váratlan pontazonosító, hibás vagy ismeretlen esemény.
- A duplikált esemény megmarad a naplóban, és hibaként jelölődik.
- A nem megfelelő oldalfal automatikusan az utómunka-sorba kerül.
- Az utómunka indítása, lezárása, megjegyzései és műveleti naplója követhető a kezelőfelületen.
- A dashboard 2 másodpercenként frissül; az MQTT monitor külön folyamatban fut.

## Követelmények

- Python 3.11 vagy újabb
- Docker Desktop (Mosquitto MQTT-brokerhez)

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

Válassz járműmodellt, ellenőrizd az Excelből beolvasott határértékeket, állíts be hibaarányt, majd indítsd el az oldalfalat. A ponttérkép a hegesztési események fogadásával frissül. A lezáráskor ellenőrzött hibás oldalfal automatikusan selejt állapotot és utómunka-bejegyzést kap.

## Tesztek

```powershell
python -m unittest discover -s tests -v
```

A tesztek lefedik a katalógus tíz konfigurációját, a modellhez tartozó pontlistát és paraméterhatárokat, a duplikációkat, a hiányzó pontokat, valamint az automatikus utómunka-sorba helyezést és az utómunka állapotátmeneteit.

## Korlát

A rendszer szoftveres demonstráció, a jármű- és technológiai adatok nem gyártói dokumentumból származnak. A modell specifikus paraméterek ellenőrzése sem bizonyítja a fizikai hegesztési kötés szilárdságát.
