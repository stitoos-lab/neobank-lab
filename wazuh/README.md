# Wazuh — règles de détection NeoBank

Ce dossier contient les règles de supervision Wazuh pour l'API NeoBank, alignées sur les actions du journal d'audit JSON produit dans `neobank/logs/api/audit.log`.

## Contenu

- `local_rules.xml` — 7 règles (100100 à 100106)
- `install.sh` — vérifie la configuration et redémarre le manager

## Installation

Prérequis : un manager Wazuh qui tourne, conteneur nommé `single-node-wazuh.manager-1` (adapter `WAZUH_CONTAINER` sinon).

Le fichier `local_rules.xml` doit être monté en bind dans le conteneur :

```yaml
# docker-compose.yml du stack Wazuh, service wazuh.manager, section volumes
- /home/eijv07/neobank-lab/wazuh/local_rules.xml:/var/ossec/etc/rules/local_rules.xml
