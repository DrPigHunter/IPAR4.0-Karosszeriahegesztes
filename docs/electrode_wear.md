# Elektródakopás, önkorrekció és eszközcsere

Ez a funkció oktatási célú szimuláció. Nem vezérel valódi hegesztőcellát, és a szintetikus minőségi mutató nem igazolja a hegesztési kötés mechanikai szilárdságát.

A paraméterek értelmezéséről, műszaki hivatkozásairól és a valós gyártási recepthez szükséges korlátozásokról lásd a [paraméter-realizmus felülvizsgálatot](parameter_realism_audit.md).

## Folyamat

1. A szimulátor az elektróda állapotát hegesztési pontokon és karosszériaciklusokon át vezeti, és a kopottságot az alkalmazás újraindítása után is megőrzi.
2. A relatív hőbeviteli proxy elektromos része az (I^2 t) összefüggésre épül. A kopási és hűtési hatás egy egyszerű, állítható paraméterű szimulációs heurisztika, nem validált fizikai modell.
3. Ha a proxy a demonstrációs 95%-os célérték alá kerül, a vezérlés az áramerősséget 0,1 kA-os lépésekben, majd szükség esetén a hegesztési időt 5 ms-os lépésekben emeli. Az Excel-katalógus adott modellhez tartozó határértékeit nem lépheti át.
4. Szándékosan, a határértékeken túlra injektált teszthibát az önkorrekció nem rejthet el. Ha a minőségi proxy határértékeken belül sem áll helyre, a monitor minőségi hibát rögzít, és az egész oldalfalat utómunkára küldi.
5. A hűtési feltételek (áramlás és belépő/kilépő vízhőmérséklet) ellenőrzése a TWI referenciaértékeihez viszonyít. Kedvezőtlen hűtés figyelmeztetést vált ki és növeli a szimulált kopási stresszt.

## Automatikus eszközcsere a szünetben

A **Statisztika és utómunka** fülön beállítható:
- a kopásmodellezés és az önkorrekció;
- a kopás szimulációs üteme pontonként;
- a hűtővíz-áramlás és a hőmérsékletek;
- az automatikus eszközcsere be-/kikapcsolása;
- az eszközcsere-intervallum, teljes baloldalfal-ciklusban;
- a csere szimulált időtartama.

A csereintervallum elérésekor a rendszer nem nullázza azonnal a kopást. A jelenlegi oldalfal befejezése után a következő ciklusok közötti szünetben futtatja a cserét. A csere a rendelkezésre álló szünetből fogyaszt időt; ha a szimulált csere tovább tart, mint a normál szünet, a leállás meghosszabbodik. A művelet naplózása után az eszköz sorszáma növekszik, az aktuális kopottság és az adott eszközre vonatkozó számlálók 0-ra állnak. A teljes élettartam-számlálók megmaradnak.

Ha az automatikus eszközcsere ki van kapcsolva, az intervallum elérésekor a gyártás megáll, és a kezelőnek kell elvégeznie a kézi cserét. A rendszer nem enged új gyártási ciklust, amíg a szükséges csere nincs rögzítve.

A kopás, az aktuális eszköz sorszáma, a függőben lévő csere és a karbantartási beállítások a `data/equipment_state.json` fájlban is megmaradnak a dashboard újraindítása után. A csereesemények az alkalmazásnaplóban és az Excel `Eszközcsere-napló` munkalapján is láthatók.

## Tesztek

```powershell
python -m unittest discover -s tests -v
```

A tesztek lefedik a kopás felhalmozását, határértékeken belüli önkorrekciót, szándékos határátlépés megőrzését, hűtési riasztásokat, szünetben végrehajtott eszközcserét, állapotmegőrzést és Excel-exportot.
