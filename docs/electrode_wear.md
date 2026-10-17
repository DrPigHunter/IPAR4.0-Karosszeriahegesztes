# Elektródakopás, önkorrekció és eszközcsere

Ez a funkció oktatási célú szimuláció. Nem vezérel valódi hegesztőcellát, és a szintetikus minőségi mutató nem igazolja a hegesztési kötés mechanikai szilárdságát.

A paraméterek értelmezéséről, műszaki hivatkozásairól és a valós gyártási recepthez szükséges korlátozásokról lásd a [paraméter-realizmus felülvizsgálatot](parameter_realism_audit.md).

## Folyamat

1. A szimulátor az elektróda állapotát hegesztési pontokon és karosszériaciklusokon át vezeti, és a kopottságot az alkalmazás újraindítása után is megőrzi.
2. A relatív hőbeviteli proxy elektromos része az (I^2 t) összefüggésre épül. A kopási és hűtési hatás egy egyszerű, állítható paraméterű szimulációs heurisztika, nem validált fizikai modell.
3. Ha a proxy a demonstrációs 95%-os célérték alá kerül, a vezérlés az áramerősséget 0,1 kA-os lépésekben, majd szükség esetén a hegesztési időt 5 ms-os lépésekben emeli. Az Excel-katalógus adott modellhez tartozó határértékeit nem lépheti át.
4. Szándékosan, a határértékeken túlra injektált teszthibát az önkorrekció nem rejthet el. Ha a minőségi proxy határértékeken belül sem áll helyre, a monitor minőségi hibát rögzít, és az egész oldalfalat utómunkára küldi.
5. A hűtési feltételek (áramlás és belépő/kilépő vízhőmérséklet) ellenőrzése a TWI referenciaértékeihez viszonyít. Kedvezőtlen hűtés figyelmeztetést vált ki és növeli a szimulált kopási stresszt.

## Automatikus hegesztőfej-/elektródaegység-csere a szimulált műszakszünetben

A kezelőfelületen a folyamatparaméterek zároltak; kizárólag a szimuláció sebessége állítható. A gyári demonstrációs beállításokat a `src/factory_settings.py` tartalmazza.

A rendszer 100 lezárt baloldalfal-ciklust tekint egy szimulált karbantartási/szüneti ciklusnak. Átlagosan 140 hegesztési ponttal ez körülbelül 14 000 hegesztési pont, ami nagyságrendileg összevethető a CORDIS SmartDress projekt elektródacsúcs-élettartam-növelési céljával. Ez nem egy konkrét üzem hivatalos műszakrendje: a valódi szünetütemezéshez az adott gyártósor taktidejét és dolgozói szünetrendjét kell megadni.

Amikor a 100. oldalfal lezárul, a rendszer nem nullázza azonnal a kopást. Ütemezi a hegesztőfej-/elektródaegység cseréjét, majd a következő karosszériák közötti állásidőben végrehajtja azt. A csere előtti állapot és az új egység naplózódik; az új egység kopása 0%-ról indul. A szimulált csereidő a karosszériák közötti szünetből fogy, és szükség esetén meghosszabbítja azt. A teljes élettartam-számlálók megmaradnak.


A kopás, az aktuális eszköz sorszáma, a függőben lévő csere és a karbantartási beállítások a `data/equipment_state.json` fájlban is megmaradnak a dashboard újraindítása után. A csereesemények az alkalmazásnaplóban és az Excel `Eszközcsere-napló` munkalapján is láthatók.

## Tesztek

```powershell
python -m unittest discover -s tests -v
```

A tesztek lefedik a kopás felhalmozását, határértékeken belüli önkorrekciót, szándékos határátlépés megőrzését, hűtési riasztásokat, szünetben végrehajtott eszközcserét, állapotmegőrzést és Excel-exportot.
