# BODYLINE bemutatóvideó – felvételi forgatókönyv

A tárgy beadási feltétele külön videót kér a rendszer működéséről. Ez a fájl nem maga a videó, hanem a rögzítés ellenőrzőlistája és a hozzá tartozó felvételi segéd használata.

## Javasolt, 3–5 perces bemutató

1. **Indítás (0:00–0:30):** a Docker Desktop és a BODYLINE PowerShell indító megmutatása; a dashboard megnyitása. Látszódjon, hogy az automatika kezdetben áll.
2. **Élő gyártás (0:30–1:30):** az automatikus modellválasztás és a sebesség megmutatása, majd gyártás indítása. A ponttérkép és az aktuális hegesztési pontok megjelenítése.
3. **Mérési csatornák (1:30–2:00):** a virtuális érzékelőket megjelenítő panel bemutatása. El kell mondani, hogy az áram-, idő- és erőértékeket a szimulátor állítja elő, nem fizikai érzékelő.
4. **Minőségfelügyelet (2:00–3:00):** teszthiba-beállítás vagy korábban keletkezett hibás darab megjelenítése; az utómunka-sor és a pontszintű hiba bemutatása.
5. **Adattárolás és adatút (3:00–4:00):** MQTT monitor/Publisher konzol, production log, SQLite-alapú statisztika és Excel-riport.
6. **Leállítás (4:00–4:30):** a biztonságos leállítás gomb, majd a leállítási napló megmutatása.

## Felvétel előtt

- Zárd be a személyes adatot tartalmazó ablakokat és értesítéseket.
- Ellenőrizd, hogy a böngésző címsora és a dashboard szövege olvasható.
- A felvételhez a `tools/Record-Bodyline-Demo.ps1` script használható. Ehhez az FFmpeg programnak telepítve kell lennie és a PATH-ban kell szerepelnie.
- A kész videót mentsd `docs/demo_video/BODYLINE_demo.mp4` néven, majd töltsd fel a Git repositoryba.

A videó elkészítése és GitHubra feltöltése külön, helyben végrehajtandó feladat; a felvételi segéd önmagában nem hoz létre valós rendszerbemutatót.
