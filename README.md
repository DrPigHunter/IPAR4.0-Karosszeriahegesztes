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

A monitor és a dashboard két külön PowerShell-ablakban fut; hagyd nyitva ezeket a szimuláció közben. Az automatika a kezelőfelület megnyitásakor **leállított állapotban** van, és az **Élő gyártás** fülön kézzel kell elindítani. A kezelőfelületen kizárólag a szimuláció sebessége állítható; a folyamatparaméterek gyári alapértékeit a `src/factory_settings.py` rögzíti. 100%-os sebességnél a rendszer a kiválasztott modell eseményszámához igazítja az események közötti várakozást, így a bal oldalfal névleges ciklusideje kb. 95 másodperc (elfogadható cél-tartomány: 90–100 másodperc). A karosszériaciklusok között ezen felül külön 10 másodperces szünet van. A sebesség 100–10 000% között állítható, az új érték a következő karosszériaciklustól érvényes. A rendszer véletlenszerűen választja ki a tíz katalógusmodell egyikét. A ciklusidő szimulációs célérték, nem garantált fizikai gyártási teljesítmény.

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
- **Statisztika és utómunka:** megfelelési/selejtarány, modellenkénti eredmények, karosszéria-előzmények és utómunka-kezelés. A normál hegesztési pontok részletes mérései nem kerülnek a TXT-naplóba.
- **Production log:** egyetlen angol nyelvű TXT-fájl, letöltéssel és két másodpercenkénti élő frissítéssel. Minden esemény azonnal, lemezre flush-olva kerül bele; darabonként rögzíti a betöltést és a gyártósorról történő levételt, külön sor csak hegesztési hibánál és utómunka-állapotváltásnál készül.
- **Kilépés és minden leállítása:** a dashboard felső részén található gomb leállítási kérést küld. Az aktuális oldalfal biztonságosan befejeződik, majd a dashboard, az MQTT-monitor és a projekt MQTT-konténere is leáll.
- **Automatizálás:** a 10 modellből a rendszer automatikusan választ, de a gyártási ciklus csak a felhasználó indításával kezdődik. Egy bal oldalfal névleges ciklusideje 95 másodperc, a cél-tartomány 90–100 másodperc; az eredményt minden lezárt ciklusnál mérjük. A két oldalfalciklus közötti 10 másodperces állásidő ettől külön értendő.
- **Folyamatparaméterek:** a külön teszthiba-injektálás alapértéke 0%, de a kopástól független háttérhiba-valószínűség 0,01% hegesztési pontonként (1:10 000). 118–142 pontos oldalfalon ez matematikailag kb. 1,17–1,41% esélyt jelent legalább egy ilyen eseményre. A szám a projekt szimulációs feltételezése, nem mért ipari hibaarány. A kopásmodell, önkorrekció, hűtés és hegesztőfej-/elektródaegység-csere kódalapú beállítások; kizárólag a `src/factory_settings.py` fájlban módosíthatók.
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

## Production TXT log

A monitor minden bejegyzést egyetlen, UTF-8 kódolású fájlba ír: `logs/production_log.txt`. A napló teljes egészében angol nyelvű, a dátumot és időt a helyi gép időzónája szerint rögzíti. Minden esemény külön append művelettel, flush és `fsync` után kerül lemezre; nem kell megvárni a program bezárását. A dashboard **Production log** füle két másodpercenként újraolvassa a fájlt, így a napló gyártás közben is követhető.

A napló darabonként az alábbi életciklus-eseményeket rögzíti:
- `NEW PART LOADED SUCCESSFULLY`: az új darab sikeresen beérkezett és regisztrálva lett.
- `PART REMOVED FROM LINE | WELDING COMPLETED SUCCESSFULLY`: a darab minden elvárt ponttal, hiba nélkül elkészült és lekerült a sorról.
- `PART REMOVED FROM LINE | WELDING FAILED | SENT TO REWORK`: a darab hibás lett, levettük a sorról és utómunkára került.
- `WELDING FAULT`: egy konkrét hegesztési pontnál tényleges hiba történt; a sor tartalmazza a darab- és pontazonosítót, a hiba okát és a mért paramétereket.
- `REWORK STARTED` és `REWORK COMPLETED | READY FOR RE-INSPECTION`: az utómunka megkezdése és lezárása.

A sikeresen meghegesztett pontok nem kapnak külön naplósort. Egy hibátlan darabról csak a betöltési és a darabszintű befejezési bejegyzés készül; külön pontszintű bejegyzés kizárólag hiba esetén keletkezik. A monitor a pontonkénti MQTT-adatokat továbbra is SQLite-ban tárolja a teljesség és a hegesztési minőség ellenőrzéséhez, de ezeket nem másolja a TXT-fájlba. A dashboard **Production log** füle megjeleníti és letölthetővé teszi ezt az egyetlen TXT-fájlt. A leállítási eseményeket is rögzíti: `APPLICATION EXIT REQUESTED` és `ALL BODYLINE SERVICES STOPPED`.

## Állítható szimulációs sebesség

Az **Élő gyártás** fülön, az indítás/leállítás gomb mellett állítható a szimuláció sebessége **100% és 10 000%** között, 100%-os lépésekkel. Alapértéke 100%. A rendszer a kiválasztott modell eseményszámából számolja az eseményközi várakozást, hogy a teljes eseménysor névlegesen 95 másodperc legyen; ezért az egyes modelleknél az eseményköz kissé eltér. Külön 10 másodperc szünet marad két karosszériaciklus között. 10 000%-nál az eseményközi várakozások nagyjából a századrészükre, a karosszériák közötti szünet pedig 0,1 másodpercre csökken. A kiválasztott sebesség a következő karosszéria-ciklustól lép életbe. A szokásos beállításváltozások nem kerülnek bele a darab- és hibaközpontú TXT-naplóba.

A 10 000% a szimulátor késleltetéseinek skálázását jelenti, nem garantál százszoros tényleges áteresztőképességet: a tényleges ciklusidőt az MQTT QoS 1 visszaigazolásai, a gép teljesítménye, az operációs rendszer és az adatbázis-feldolgozás is korlátozza. Minden ciklusnál ténylegesen mérjük az időt, és 100 másodperc alatt tekintjük a ciklust célon belülinek. A célérték a bal oldalfalra vonatkozik, nem egy teljes járműkarosszériára. Az automata az MQTT-broker visszaigazolásai után a monitor adatbázisában is megvárja a karosszéria végleges minősítését. Ha a monitor 30 másodpercen belül nem véglegesít, vagy bármilyen ciklusküldési/feldolgozási hiba történik, a gyártási folyamat biztonsági okból leállítja a további küldést, és hibát naplóz ahelyett, hogy korlátlanul felhalmozná az eseményeket. A hiba elhárítása után az operátor kézzel indíthatja újra.

## Elektródakopás, hűtés, önkorrekció és eszközcsere

A fejlesztési ág kopási indexet, (I^2 t) alapú szintetikus hőbeviteli közelítést és határértékek közötti önkorrekciót modellez. A kopási, hűtési, önkorrekciós és hegesztőfej-/elektródaegység-csere-paraméterek a `src/factory_settings.py` fájlban rögzítettek; a kezelőfelületen ezek nem állíthatók.

Az elektródakopás a karosszériaciklusok között is megmarad, és a `data/equipment_state.json` fájlban újraindítás után is folytatódik. A kódalapú beállítás 100 lezárt bal oldalfal után indít egy **szimulált műszakszüneti karbantartási pontot** (kb. 14 000 hegesztési pont 140 pont/oldalfal mellett). Az intervallum elérése után a hegesztőfej/elektródaegység cseréje a következő karosszériák közötti állásidőben történik; a régi egység állapota naplózódik, majd az új egység kopása 0%-ról indul. A csere a rendelkezésre álló szünetből fogyaszt időt; hosszabb csere esetén az állásidő is hosszabb. Ez a szimuláció ciklusszám alapján közelíti a karbantartási szünetet, nem modellez konkrét vállalati műszak- vagy pihenőidő-naptárt.

A kopás és az eszközcsere állapota a futás közben a kezelőfelületen követhető. Ezek a normál karbantartási események nem kerülnek a rövid gyártási TXT-naplóba; figyelmeztetés vagy rendszerhiba esetén külön rendszerbejegyzés készül.

**Műszaki korlátozás:** az áramlépés/önkorrekció, kopásráta, csereintervallum, csereidő és a 95%-os minőségi proxy demonstrációs paraméterek, nem hitelesített gyári receptértékek. A hűtés alapértékei a TWI bevonatos/vastagabb acélhoz adott referenciaértékei (6 l/perc, max. 20 °C belépő és 30 °C kilépő), de más anyag-/pisztoly-/hűtőrendszer esetén ezeket az adott berendezés specifikációja szerint kell beállítani. A dashboard referencia-auditja csak széles plausibilitási szűrő; nem helyettesít anyag- és illesztésspecifikus hegesztési tartományvizsgálatot.

A kopástól független hibamódok forrásai: [TWI – hegesztési minőség és folyamatváltozók](https://www.twi-global.com/technical-knowledge/faqs/faq-what-must-be-done-to-ensure-the-quality-and-consistency-of-resistance-spot-welds) és [ISIJ International – ponthegesztési hibák vizsgálata](https://www.jstage.jst.go.jp/article/isijinternational/54/8/54_1883/_html/-char/en). Források és részletes felülvizsgálat: [Paraméter-realizmus audit](docs/parameter_realism_audit.md), [Elektródakopás és eszközcsere dokumentáció](docs/electrode_wear.md).

## Tesztek futtatása

    python -m unittest discover -s tests -v

A tesztek ellenőrzik a katalógus szerkezetét, a szimulátor eseménysorát, a paraméterhatárokat, a hiányzó és duplikált pontokat, az automatikus utómunka-kezelést, a 100–10 000%-os sebességskálázást, a sorrendtartó MQTT-küldést, a monitor véglegesítésére várást, a darabonkénti angol TXT-naplót, a pontszintű hibanaplózást és az utómunka állapotváltásait. A GitHub Actions külön, valódi Mosquitto-brokerrel is végigteszteli az MQTT → monitor → SQLite folyamatot hibátlan és szándékosan hibás karosszériával.


## Kilépés és teljes leállítás

A dashboard felső részén lévő **Kilépés és minden leállítása** gomb a `tools/Stop-Bodyline.ps1` folyamatot indítja el. A leállítás menete:
1. A program leállítási kérést jelez a gyártási workernek és az MQTT-monitornak.
2. Ha egy oldalfal ciklusa éppen fut, a worker befejezi a teljes aktuális ciklust, a monitor elmenti a végleges minősítést, és csak ezután jelzi a biztonságos leállási pontot.
3. A dashboard és a monitor szolgáltatásfolyamata, valamint a hozzájuk tartozó PowerShell-ablakok leállnak.
4. A projekt `mqtt` Docker Compose szolgáltatása leáll. A Docker Desktop maga továbbra is futva marad.
5. A TXT-naplóba bekerül az `ALL BODYLINE SERVICES STOPPED` bejegyzés.

Ha a ciklus 150 másodpercen belül nem jut el biztonságos leállási pontra, a leállító szkript figyelmeztetést ír a naplóba, majd leállítja a projekt szolgáltatásait. A normál leállítás tehát megvárja a folyamatban lévő oldalfalat, a vészleállítás pedig nem hagyja korlátlanul futni a folyamatokat.

## Ismételt, duplikációmentes indítás

A Start_HegesztesSzimulacio.ps1 indítószkript biztonságosan újrafuttatható:
- ha az indítás már folyamatban van, a második példány nem indít újabb szolgáltatásokat;
- ha a BODYLINE dashboard már egészségesen fut ezen a projekten, a szkript újrahasználja, nem nyit új böngészőablakot;
- a régi, ehhez a projekthez tartozó monitor/dashboard folyamatokat indítás előtt leállítja;
- a dashboard csak akkor nyitja meg a böngészőt egyszer, ha a http://localhost:8501/_stcore/health ellenőrzése sikeres;
- sikertelen indításnál nem nyit meg üres böngészőoldalt, hanem a logs/monitor.log és logs/dashboard.log naplókat jelöli meg hibakereséshez.

Ha a localhost:8501 portot egy másik alkalmazás használja, az indítószkript nem indít rá második Streamlit-példányt: jelzi a foglalt portot és a folyamat PID-jét.

## Hálózati beállítás – helyi gép vagy LAN

Alapértelmezésben a szimulátor és a monitor a helyi `127.0.0.1:1883` Mosquitto brokerhez csatlakozik. Ha a broker egy másik gépen fut a helyi hálózaton, az indító PowerShell-ablakban a program indítása előtt állítsd be a környezeti változókat:

```powershell
$env:BODYLINE_MQTT_HOST = "192.168.1.50"
$env:BODYLINE_MQTT_PORT = "1883"
$env:BODYLINE_MQTT_TOPIC = "welding/events"
.\Start_HegesztesSzimulacio.ps1
```

A `192.168.1.50` csak példa; a Docker/Mosquitto host tényleges IP-címét add meg. A broker portját a host tűzfalán a megbízható magánhálózati profilhoz kell engedélyezni. A publisher és a monitor ugyanazt a host/port/topic beállítást használja; a dashboard a monitor közös konfigurációját importálja.

**Biztonság:** a mellékelt Mosquitto-konfiguráció anonim és titkosítatlan, ezért ez csak elkülönített oktatási hálózatban használható. A 1883-as portot ne tedd elérhetővé az internet felől. Üzemi használathoz hitelesítés, ACL, TLS és tűzfalszabályok szükségesek.

## Virtuális érzékelők és beavatkozási pontok

Az Élő gyártás fülön lenyitható a **Virtuális érzékelők, beavatkozási és kezelői pontok** panel. A projekt három virtuális mérőcsatornát használ: hegesztőáram (kA), hegesztési idő (ms) és elektródaerő (kN). Mindhárom egy-egy értéket ad minden hegesztési pont eseményéhez. A hegesztési esemény jelzi a virtuális csatornaazonosítót és azt, hogy az adat szimulált. Nincs valós érzékelő a rendszerhez csatlakoztatva.

A logikai beavatkozási pontok a határok közötti paraméterkorrekció, az utómunka-sorba irányítás és a szimulált elektródaegység-csere. Ezek szoftveres döntések, nem fizikai aktuátorok. Az operátori interakciók: gyártásindítás/leállítás, sebességbeállítás, utómunka START/COMPLETE és riportexport.

## UML-tervek és architektúra

A `docs/uml/` mappa PlantUML forrásokat tartalmaz a használati esetekhez, telepítési nézethez, aktivitásdiagramhoz és munkadarab-állapotgéphez. A részletes 0. rendű adatfolyamdiagram, a mérési csatornák, az aktuátorhelyettesítések és a hálózati felépítés a `docs/architecture.md` fájlban található.

PlantUML képek készítéséhez telepített PlantUML és Java szükséges:

```powershell
plantuml -tsvg docs/uml/*.puml
```

## Bemutatóvideó rögzítése

A tárgy külön videót kér a rendszer működéséről. A felvételhez telepített FFmpeg mellett futtasd:

```powershell
.\tools\Record-Bodyline-Demo.ps1 -DurationSeconds 240
```

A segéd a teljes asztalt rögzíti, ezért előtte zárd be a személyes adatokat tartalmazó ablakokat. A felvétel javasolt helye: `docs/demo_video/BODYLINE_demo.mp4`. A forgatókönyv a `docs/video_demo_script.md` fájlban található. A felvétel és az MP4 GitHubra feltöltése kézzel végrehajtandó beadási lépés.
