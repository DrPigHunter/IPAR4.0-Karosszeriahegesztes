# Elektródakopás és automatikus önkorrekció

Ez a funkció külön fejlesztési ágban készült oktatási demonstrációként. Nem valódi hegesztőcellát vezérel, és az itt használt minőségi mutató nem igazolja a fizikai kötés szilárdságát.

## Folyamat

1. A szimulátor ciklusok és hegesztési pontok között megőrzi az elektróda kopási állapotát.
2. Minden pont után növeli a beállított kopási százalékot, és ebből egy szintetikus hőbeviteli/minőségi mutatót számol.
3. Ha az érték a 95%-os célérték alatt van, az önkorrekció először az áramerősséget, majd — ha az áram elérte a katalógus határát — a hegesztési időt emeli.
4. Minden módosítás az Excel-katalógus adott modellhez tartozó határértékein belül marad.
5. Ha a célérték határértéken belül nem érhető el, az esemény `process_quality_ok=false` jelölést kap; a monitor minőségi hibát rögzít, és a teljes oldalfalat utómunkára irányítja.

A vezérlő nem módosítja automatikusan az elektródaerőt, és nem írja át az Excel-referenciakatalógust. A kopási ráta, a minőségi index és a célérték szintetikus paraméterek, nem ipari receptértékek.

## Kezelőfelület

A **Statisztika és utómunka** fülön állítható:
- a kopásmodell be-/kikapcsolása;
- a kopás üteme hegesztési pontonként;
- az automatikus önkorrekció be-/kikapcsolása.

A panel mutatja a felhalmozott kopást, a pontszámot, a sikeres korrekciók és a sikertelen korrekciók darabszámát. Az **Elektróda cseréje / kopás nullázása** gomb csak leállított gyártásnál használható, és naplózza a szimulált elektródacserét. Az élő gyártás panel karosszériánként jeleníti meg a korrigált pontokat, a korrekciós lépések számát és a sikertelen pontokat. A részletes hegesztési esemény a SQLite `raw_json` mezőjében marad meg, így az Excel-kiadásban is elérhető.

## Teszt

```powershell
python -m unittest discover -s tests -v
```

A `tests/test_wear_control.py` ellenőrzi a kopás felhalmozását, a beállítások kikapcsolt állapotát, a határértékek megtartását és azt, hogy a sikertelen korrekciót a monitor utómunkára küldi.
