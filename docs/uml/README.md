# BODYLINE UML-tervforrások

A rendszer tervezési nézeteit PlantUML-forrásként tartalmazza a mappa. A fájlok a projekt fő használati eseteit, telepítési nézetét, adatfeldolgozási folyamatát és munkadarab-állapotgépét írják le.

- `bodyline_use_cases.puml`: operátor és rendszer használati esetei.
- `bodyline_deployment.puml`: komponensek és csomópontok telepítési nézete, helyi hálózati MQTT-kapcsolattal.
- `bodyline_activity.puml`: hegesztési események útja a virtuális jel előállításától a minősítésig.
- `bodyline_state_machine.puml`: a munkadarab és az utómunka állapotátmenetei.

A rajzok a jelenlegi szoftveres demonstrációt írják le. A virtuális szenzorok, a logikai aktuátorok és a fizikai hardver közötti különbség szándékosan jelölve van; valós érzékelő vagy beavatkozó nincs a rendszerre kötve.

PlantUML-lel PNG vagy SVG formátum készíthető:

```powershell
plantuml -tsvg docs/uml/*.puml
```
