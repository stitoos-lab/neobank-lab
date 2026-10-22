# Lab phase 1 : segmentation en trois zones

| Source | Destination | Autorisé | Raison |
| --- | --- | --- | --- |
| Hôte (127.0.0.1) | web : 8080 | Oui | Seul point d'entrée |
| web | api | Oui | Le proxy relaie vers l'application |
| api | db | Oui | L'application lit et écrit les données |
| web | db | **Non** | Zone 'data' en réseau interne |

Zones 'dmz' (web), 'app' (web, api), 'data' (api, db).
