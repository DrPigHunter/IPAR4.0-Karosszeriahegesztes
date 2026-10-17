# Hegesztési paraméterek és valósághűségi felülvizsgálat

## Mit ellenőriz a projekt?

A `Statisztika és utómunka` fül **Hegesztési recept – műszaki referencia-ellenőrzés** panelje konfigurációnként megmutatja a katalógusban lévő áram-, idő- és elektródaerő-határokat, valamint a névleges pontprogram min/max értékeit. Ugyanez a táblázat az Excel-export `Paraméter-audit` munkalapjára is bekerül.

A teszt csak **széles plausibilitási szűrő**. Nem igazolja, hogy az adott értékek megfelelőek egy konkrét OEM gyártósorhoz. A valós recept meghatározásához szükséges legalább: anyagminőség, lemezvastagság és rétegrend, bevonat, hézag/illesztés, elektróda sapkageometria és anyag, hegesztőpisztoly/vezérlő, hűtési rendszer, valamint validált hegesztési tartományvizsgálat.

## Forrásból származó referenciaértékek

- **Hőbevitel:** az ellenállás-ponthegesztés egyszerű elektromos hőtermelési összefüggése (Q approx I^2 R t). A tényleges ellenállás a munkadarab anyagától/felületétől, az elektródától és az elektródaerőtől is függ. Forrás: European Aluminium Association, *Resistance Welding* (2015), 1. oldal.
- **Acél áramerőssége és elektródaereje:** az EAA útmutató szerint acélhoz rendszerint 15 kA alatti áram és 0,2–4 kN elektródaerő elegendő. Ez tájékoztató tartomány, nem univerzális specifikáció.
- **Egy konkrét nagy szilárdságú acél példa:** a *Welding in the World* folyóirat 22MnB5+AS150, összesen 1,5 mm vastag próbatesteken 4,6–6,0 kA közötti hegesztési tartományt mért; több elektródaerőt vizsgált, köztük 2,5–5,5 kN-t és egy kiterjesztett vizsgálatban 2,0–6,0 kN-t. Ezek a számok csak arra a vizsgált anyag-/illesztés-/elektródaelrendezésre vonatkoznak.
- **Elektródahűtés:** a TWI 4 l/percet ajánl vékony, bevonat nélküli acélhoz; bevonatos vagy vastagabb acélhoz legalább 6 l/percet, legfeljebb 20 °C belépő és 30 °C kilépő hűtővizet javasol. Ezért az alap forgatókönyv bevonatos autóipari acélra 6 l/perc, 20 °C és 30 °C. Ha a valós sor más anyagot vagy hűtőegységet használ, az értékeket annak specifikációja szerint kell beállítani.
- **Kopás és karbantartás:** a TWI az elektróda kopását termikus és mechanikai hatásokhoz, bevonatos anyag esetén a felület ötvöződéséhez köti. A kopás mérséklésére megfelelő hűtést, anyagot/geometriát és illesztést, karbantartásra elektróda-dresszelést és/vagy lépésenkénti áramkompenzációt említ. A CORDIS SmartDress projekt optikai kopásfigyelést, adaptív dresszelési ütemezést és automatikus hegycserét vizsgál; ez alátámasztja, hogy a karbantartási időzítés ideálisan az eszköz tényleges állapotához igazodik, nem minden cellára azonos fix ciklusszám.

### Források

1. European Aluminium Association, *Resistance Welding* (2015): https://european-aluminium.eu/wp-content/uploads/2022/11/5-resistance-welding_2015.pdf
2. Wohner et al., *Resistance spot welding with variable electrode force—development and benefit of a force profile to extend the weldability of 22MnB5+AS150*, Welding in the World: https://link.springer.com/article/10.1007/s40194-020-01001-2
3. TWI, *How can I minimise electrode wear in resistance spot welding?*: https://www.twi-global.com/technical-knowledge/faqs/faq-how-can-i-minimise-electrode-wear-in-resistance-spot-welding
4. European Commission CORDIS, *Adaptive Tip dress Control for Automated Resistance Spot Welding (SmartDress)*: https://cordis.europa.eu/project/id/286598/reporting/de

## Beállítások a demonstrációban

| Paraméter | Alapérték | Értelmezés |
|---|---:|---|
| Pontáram / hegesztési idő / elektródaerő | Modell Excel-katalógusa szerint | Szintetikus pontprogram; az audit megjeleníti az értékeket, de nem minősíti őket OEM receptként. |
| Önkorrekciós áramlépés | 0,1 kA | Demonstrációs lépés; a szakirodalom dokumentál lépcsőzetes áramkompenzációt, de a pontos lépést folyamatpróbán kell rögzíteni. |
| Önkorrekciós időlépés | 5 ms | Numerikus szimulációs lépés, nem gyártói érték. |
| Szintetikus minőségi cél | 95% | Demonstrációs hőbeviteli proxy küszöbe, nem szabványos elfogadási határ. |
| Kopásnövekedés | 0,005 százalékpont / pont | Állítható szimulációs paraméter. Nem egy gyárban mért valódi elektródakopási sebesség. |
| Csereintervallum | 100 lezárt **baloldalfal-ciklus** | Szemléltető alapérték. A ciklus itt egyetlen oldalfal-pontprogram, nem egy teljes autó. Valós üzemhez a tényleges karbantartási előzményből kell beállítani. |
| Szimulált eszközcsere-idő | 5 másodperc | A gépi modell szünetéből elfogyasztott szimulációs idő, nem állítás az ipari hegycserélő fizikai idejéről. |
| Hűtővíz | 6 l/perc; 20 °C be; 30 °C ki | TWI referencia bevonatos/vastagabb acélhoz. A hűtési értékek eltérésénél figyelmeztetés és magasabb szimulált kopási stressz jelenik meg. |
| Pontonkénti hibainjektálás | Alapból 0%; legfeljebb 0,1% | Tesztparaméter a felügyeleti rendszer bemutatására, nem valós gyári selejtarány. |
| MQTT-küldési késleltetés | 90 ms pontonként 100%-os szimulációs sebességnél | Dashboard/telemetria-időzítés; nem a fizikai hegesztőáram bekapcsolási ideje. |

A kopásmodell az (I^2 t) összefüggésből indul ki, majd a kopás és a hűtési kockázat hatását **egyszerű, kifejezetten heurisztikus szorzóként** veszi figyelembe. Az önkorrekció csak a modell Excel-katalógusának megengedett áram- és időhatárain belül működhet. A tényleges hegesztési minőség igazolásához dinamikus ellenállás-/áram-/feszültségjelek, elektródakopás- vagy hegygeometria-mérés, valamint megfelelő próbadarab- és kötésvizsgálat szükséges.

## Eszközcsere a szünetben

Az eszközcsere-intervallum elérésekor a rendszer **nem nullázza azonnal** a kopást. Megjelöli a cserét, lezárja a karosszériát, és a következő ciklusok közötti szünetben hajtja végre a szimulált cserét. A normál 10 másodperces szünetből a beállított 5 másodperces csereidő fogy; ha a csereidő a szünetnél hosszabb, a leállás meghosszabbodik. Ezután nő az eszköz sorszáma, 0%-ra áll az aktuális kopás, és lenullázódnak az aktuális eszköz statisztikái. Az összes élettartam-statisztika megmarad.

Ha az automatikus csere ki van kapcsolva, a gyártás az intervallum elérésekor leáll és kézi cserét kér. A kopási állapot a `data/equipment_state.json` állományba is mentődik, ezért az alkalmazás újraindítása nem indítja újra nulláról az eszköz élettartamát. A csere a kezelői naplóba és az Excel `Eszközcsere-napló` munkalapjára kerül.

## Fontos korlátozás

A projekt oktatási szimuláció; nem vezérel valódi hegesztőcellát. A hűtési referenciaértékeken kívül a kopási százalék, az automatikus csere alapértelmezett ciklusszáma, a csereidő és a 95%-os minőségi proxy **nem irodalomból átvett gyári beállítás**. Ezek szimulációs kezdőértékek, és kizárólag validált, adott anyag-/illesztés-/pisztolyrecepttel és folyamatadatokkal kalibrálhatók ipari használathoz.
