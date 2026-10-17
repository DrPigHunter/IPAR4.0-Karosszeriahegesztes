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

A monitor és a dashboard két külön PowerShell-ablakban fut; hagyd nyitva ezeket a szimuláció közben. Az automatika a kezelőfelület megnyitásakor **leállított állapotban** van: a hibaarány és a sebesség beállítása után az **Élő gyártás** fülön kézzel kell elindítani. 100%-os sebességnél a pontküldések közötti alapvárakozás 90 ms, a karosszériák között 10 másodperc. A kezelőfelületen a sebesség 100–10 000% között állítható, és az új érték a következő karosszériaciklustól érvényes. A rendszer véletlenszerűen választja ki a tíz katalógusmodell egyikét. A 20 másodperces cikluscél mérendő elvárás, nem garantált teljesítmény.

## Kézi indítás

A projekt gyökérmappájában, ha a virtuális környezet még nem létezik:

    py -3 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt

Indítsd el a Docker Desktopot, majd:

    docker compose up -d mqtt

Egy külön PowerShell-ablakban indítsd el a monitort:

    .\.venv\Scripts\Activate.ps1
    python -m src.monitor

Egy másik ablakban indítsd a webes kezelőfelületet:

    .\.venv\Scripts\Activate.ps1
    streamlit run src/dashboard.py

Ezután nyisd meg a http://localhost:8501 címet. Az automatika nem indul el magától.

## Háromfüles felület

- **Élő gyártás:** aktuális karosszéria, pontteljesség és színkódolt ponttérkép, indítás/leállítás és sebességszabályzó 100–10 000% között.
- **Statisztika és utómunka:** megfelelési/selejtarány, modellenkénti eredmények, hibaarány és hibamód beállítása, karosszéria-előzmények, mérési napló és utómunka-kezelés.
- **Napló és export:** tartós futás- és alkalmazásnaplók, monitor/dashboard konzolnaplók, dátumozott Excel-jelentés és letöltés.
- **Automatizálás:** a 10 modellből a rendszer automatikusan választ, de a gyártási ciklus csak a felhasználó indításával kezdődik. A ciklusidő célértéke 20 másodperc alatt; az eredményt minden lezárt ciklusnál mérjük.
- **Pontonkénti eltérésvalószínűség:** a Statisztika és utómunka fülön 0,000–0,100% között állítható, 0,001 százalékpontos lépésekkel. A 0,000% kikapcsol minden mesterséges eltérést.
- **Eltérési mód:** választható elfogadott tartományon belüli változtatás (megfelelő marad), vagy a határértéket egy mérési lépéssel átlépő hiba (utómunka).
- **Utómunka:** a ténylegesen hiányzó pont, határértéken kívüli paraméter, duplikált vagy váratlan pont hibának számít, és automatikusan utómunka-sorba kerül.
- **Statisztika:** az aktuális dashboard-folyamat új futásait külön számolja; a korábbi futások megmaradnak az előzményekben, így régi selejtek nem torzítják az új menet mérőszámait.

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

## Állítható szimulációs sebesség

Az **Élő gyártás** fülön, az indítás/leállítás gomb mellett állítható a szimuláció sebessége **100% és 10 000%** között, 100%-os lépésekkel. Alapértéke 100%, ami pontosan a korábbi beállításokat jelenti: 90 ms késleltetés hegesztési eseményenként és 10 másodperc szünet két karosszéria között. 10 000%-nál ezek az ütemezett várakozások 0,9 ms-ra, illetve 0,1 másodpercre csökkennek. A kiválasztott érték a következő karosszéria-ciklustól lép életbe, és az alkalmazásnaplóban, valamint az Excel-jelentésben is rögzül.

A 10 000% a szimulátor késleltetéseinek skálázását jelenti, nem garantál százszoros tényleges áteresztőképességet: a tényleges ciklusidőt az MQTT QoS 1 visszaigazolásai, a gép teljesítménye, az operációs rendszer és az adatbázis-feldolgozás is korlátozza. A 20 másodperces célértéket minden ciklusnál továbbra is ténylegesen mérjük. Az automata az MQTT-broker visszaigazolásai után a monitor adatbázisában is megvárja a karosszéria végleges minősítését. Ha a monitor 30 másodpercen belül nem véglegesít, vagy bármilyen ciklusküldési/feldolgozási hiba történik, a gyártási folyamat biztonsági okból leállítja a további küldést, és hibát naplóz ahelyett, hogy korlátlanul felhalmozná az eseményeket. A hiba elhárítása után az operátor kézzel indíthatja újra.

## Kijelentkezés, Excel-értékelés és teljes napló

A dashboard jobb felső **Kijelentkezés + Excel** gombja dátum- és időbélyeggel ellátott XLSX-jelentést készít a `logs/exports` mappába, és letölthetővé teszi a böngészőben. Az export létrehozása **nem függ attól, hogy az automatika magától leáll-e**: a program először elmenti az aktuális állapotot, majd megkísérli a gyártási szál rendezett leállítását, és frissíti a munkafüzetet, ha újabb adatok érkeztek.

Ha valamelyik adatlapon túllépné az Excel 1 048 576 soros korlátját, a jelentés több számozott munkalapra bontja az adatokat, és egyetlen sort sem hagy ki.

A jelentés munkalapjai többek között:
- `Összesítő`: darabszámok, megfelelési és selejtarány, ciklusidők, hibák és utómunka.
- `Modellenként`: modellenkénti minőségi eredmények és időadatok.
- `Karosszériák` és `Hegesztési adatok`: **az összes elérhető SQLite-rekord**, nem csupán a képernyőn látható sorok.
- `Utómunka sor`, `Utómunka műveletek`, `Rendszerhibák`: utómunka- és hibabejegyzések.
- `Futásnaplók`, `Napi JSONL`, `Összesített JSON`, `Alkalmazás-napló`, `Konzolnapló`: ciklus- és programnaplók.
- `Beállítások`: a jelentéskészítéskor kiválasztott hibaarány, hibamód és sebesség.

A **Napló és export** fül az adatbázis összes karosszéria-, hegesztési pont-, utómunka- és rendszerhiba-bejegyzését, a JSON/JSONL naplókat, az alkalmazásnaplót, a monitor/dashboard konzolnaplókat és a már mentett Excel-exportok listáját jeleníti meg. A gombnyomások, hibabeállítás-változások, karosszériánként használt hibaarányok, ciklusidők és indítási/leállítási kérések napi alkalmazásnaplóba íródnak. Az indítószkript a monitor és a dashboard kimenetét is a logs/monitor.log és logs/dashboard.log fájlokba irányítja. A mérési adatok SQLite-ban, a lezárt ciklusok JSON/JSONL-fájlokban folyamatosan megmaradnak akkor is, ha a kezelőfelület váratlanul bezáródik.

Az Excel-fájlok helye helyi futtatáskor: `logs/exports/BODYLINE_jelentes_ÉÉÉÉ-HH-NN_ÓÓ-PP-MP_ffffff.xlsx`.


## Elektródakopás, hűtés, önkorrekció és eszközcsere

A külön fejlesztési ág kopási indexet, (I^2 t) alapú szintetikus hőbeviteli közelítést és határértékek közötti önkorrekciót modellez. A Statisztika és utómunka fülön beállítható a kopási ütem, a hűtővíz-áramlás és a belépő/kilépő hőmérséklet, valamint az automatikus eszközcsere.

Az elektródakopás a karosszériaciklusok között is megmarad, és a `data/equipment_state.json` fájlban újraindítás után is folytatódik. A csereintervallum **lezárt baloldalfal-ciklusban** állítható. Az alapértelmezett 100 ciklus nagyjából 14 000 pontot jelent, ha egy oldalfalon kb. 140 pont szerepel; ez nagyságrendileg összevethető a CORDIS SmartDress 10 000–30 000 pontos fejlesztési céljával, de nem univerzális élettartam-előírás. Az intervallum elérése után az eszközcsere a következő ciklusok közötti szünetben történik: a régi eszköz állapota naplózódik, majd az új eszköz kopása 0%-ról indul. A szimulált csereidő a normál szünetből fogy; hosszabb csere esetén a leállás is hosszabb. Automatikus csere kikapcsolásakor a gyártás biztonságosan megáll, és kézi eszközcserét kér.

Az Excel-export külön `Kopás és önkorrekció`, `Eszközcsere-napló`, `Paraméter-audit` és `Források` munkalapokat tartalmazza, így a felhasznált hűtési referenciaértékek és az egyedi tanulmányokra vonatkozó korlátozások a jelentésben is visszakereshetők.

**Műszaki korlátozás:** az áramlépés/önkorrekció, kopásráta, csereintervallum, csereidő és a 95%-os minőségi proxy demonstrációs paraméterek, nem hitelesített gyári receptértékek. A hűtés alapértékei a TWI bevonatos/vastagabb acélhoz adott referenciaértékei (6 l/perc, max. 20 °C belépő és 30 °C kilépő), de más anyag-/pisztoly-/hűtőrendszer esetén ezeket az adott berendezés specifikációja szerint kell beállítani. A dashboard referencia-auditja csak széles plausibilitási szűrő; nem helyettesít anyag- és illesztésspecifikus hegesztési tartományvizsgálatot.

Források és részletes felülvizsgálat: [Paraméter-realizmus audit](docs/parameter_realism_audit.md), [Elektródakopás és eszközcsere dokumentáció](docs/electrode_wear.md).

## Tesztek futtatása

    python -m unittest discover -s tests -v

A tesztek ellenőrzik a katalógus szerkezetét, a szimulátor eseménysorát, a paraméterhatárokat, a hiányzó és duplikált pontokat, az automatikus utómunka-kezelést, a 100–10 000%-os sebességskálázást, a sorrendtartó MQTT-küldést, a monitor véglegesítésére várást, a teljes Excel-exportot és a nagy munkalapok biztonságos darabolását. A GitHub Actions külön, valódi Mosquitto-brokerrel is végigteszteli az MQTT → monitor → SQLite folyamatot hibátlan és szándékosan hibás karosszériával.
