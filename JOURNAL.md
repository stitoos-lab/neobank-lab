# Journal des incidents et apprentissages

Ce document trace les problèmes techniques rencontrés durant la construction du Lab et leurs résolutions.

### 1. Conflit de dépendances Python : `psycopg` vs Docker Alpine
- **Symptôme** : L'API crashe au démarrage avec l'erreur `ImportError: no pq wrapper available` ou `libpq library not found`.
- **Cause** : Le paquet `psycopg` nécessite la librairie C système `libpq-dev` pour compiler, absente des images Docker Python minimalistes (`alpine` ou `slim`).
- **Solution** : Utiliser `psycopg[binary]` dans le `requirements.txt` pour télécharger la version pré-compilée embarquant ses propres librairies système.

### 2. Limite matérielle de Bcrypt avec Passlib
- **Symptôme** : Erreur 500 au démarrage avec `ValueError: password cannot be longer than 72 bytes`.
- **Cause** : La mise à jour de `bcrypt` vers sa version 4+ a introduit une vérification stricte de la limite historique de l'algorithme (72 octets). L'auto-test de sécurité au lancement de `passlib` utilise une chaîne de test dépassant cette taille, provoquant un crash.
- **Solution** : Forcer une version compatible (`bcrypt==4.0.1` ou version antécédente) ou contourner l'auto-test.

### 3. Rejet silencieux des requêtes par Nginx (Erreur 400)
- **Symptôme** : Les requêtes `curl` renvoient une erreur 400 Bad Request générée par Nginx avant même de toucher l'API FastAPI.
- **Cause** : Espace inséré par erreur dans l'en-tête HTTP (ex: `Content-Type : application/json`). Les serveurs web modernes respectent strictement la RFC 7230 pour prévenir les attaques de type *HTTP Request Smuggling*.
- **Solution** : Corriger la syntaxe de l'en-tête (`Content-Type: application/json`).

### 4. Piège de syntaxe avec Docker Compose Exec
- **Symptôme** : L'exécution d'une commande dans le conteneur de base de données renvoie `service "psql" is not running`.
- **Cause** : Oubli de spécifier le nom du service Docker cible (`db`) avant la commande à exécuter. Docker interprète `psql` comme étant le nom du service.
- **Solution** : Respecter l'ordre strict `docker compose exec <service> <commande>` (ex: `docker compose exec db psql -U ...`).

### 5. Absence du module `venv` sous Ubuntu
- **Symptôme** : L'exécution de `python3 -m venv .venv` échoue en indiquant que `ensurepip` n'est pas disponible.
- **Cause** : Contrairement aux installeurs Windows/macOS, les distributions basées sur Debian séparent l'environnement virtuel du paquet Python principal pour alléger le système.
- **Solution** : Installer le paquet système `sudo apt install python3.12-venv`.

### 6. Journal d'audit jamais écrit sur le disque (supervision aveugle)
- **Symptôme** : Wazuh signalait `ERROR: (1103): Could not open file '.../logs/api/audit.log'` (No such file or directory), alors que l'API tournait sans erreur.
- **Cause** : double négligence. (1) La fonction `audit()` dans `main.py` n'écrivait que dans PostgreSQL, jamais dans un fichier. (2) Même si elle l'avait fait, le fichier aurait été à l'intérieur du conteneur, invisible pour l'agent Wazuh qui tourne sur l'hôte.
- **Solution** : ajout d'un `logging.FileHandler` dans `main.py` qui écrit du JSON-lignes dans `/var/log/neobank/audit.log`, et ajout du volume `./logs/api:/var/log/neobank` dans `neobank/docker-compose.yml`. L'agent Wazuh sur l'hôte lit maintenant `logs/api/audit.log` sans problème.

### 7. Blocs `<localfile>` dupliqués dans `ossec.conf`
- **Symptôme** : `WARNING: (1958): Log file '.../logs/api/audit.log' is duplicated.`
- **Cause** : le bloc de configuration avait été ajouté plusieurs fois lors des essais successifs (scripts python d'édition qui ne vérifiaient pas l'existence avant ajout).
- **Solution** : script python avec `re.findall` qui détecte tous les blocs `<localfile>...</localfile>` contenant le chemin cible, garde le premier, supprime les autres.

### 8. Champ `action` refusé par le moteur de règles Wazuh
- **Symptôme** : `ERROR: Failure to read rule 100100. Field 'action' is static.` puis `CRITICAL: (1220): Error loading the rules`. `analysisd` refuse de démarrer, `wazuh-logtest` échoue en cascade (`error when connecting with wazuh-analysisd`).
- **Cause** : `action` est un champ **réservé** dans le décodeur interne de Wazuh. Une règle qui fait `<field name="action">...</field>` est rejetée au chargement.
- **Solution** : renommage de la clé JSON côté API : `action` → `audit_action`. Côté règle Wazuh, `<field name="audit_action">login_failed</field>`. ⚠️ Le champ `srcip` reste inchangé (lui est statique et légitime pour la corrélation IP).

### 9. `Permission denied` (errno 13) au chargement des règles
- **Symptôme** : `(1103): Could not open file 'etc/rules/local_rules.xml' due to [(13)-(Permission denied)]`. Le fichier existait pourtant.
- **Cause** : lors de l'écriture via `docker exec -u root` (nécessaire pour toucher `/var/ossec/etc/`), le fichier est recréé avec owner `root:root` mode `644`. Or `wazuh-analysisd` tourne sous l'utilisateur `wazuh` (uid 999) : il ne peut pas lire un fichier dont il n'est pas propriétaire.
- **Piège annexe** : exécuter `chown` / `chmod` depuis l'hôte (`eijv07@ubuntu`) ne fonctionne pas — ces commandes doivent tourner **dans** le conteneur via `docker exec`, sauf si le fichier est bind-monté (voir entrée 11).
- **Solution** : soit `chown wazuh:wazuh` + `chmod 660` **dans le conteneur** (ancien setup, avant bind mount), soit en bind mount : `chmod 644` côté hôte owned par l'utilisateur hôte — wazuh (999) accède alors via « others » (voir entrée 11).

### 10. Édition du fichier impossible via l'extension Docker de VS Code
- **Symptôme** : `Failed to save: ChildProcessError: Error response from daemon: RemoveAll local_rules.xml: device or resource busy`.
- **Cause** : une fois `local_rules.xml` dans un bind mount, l'extension Docker de VS Code (qui sauvegarde en supprimant puis recréant le fichier) ne peut plus le modifier — le mount est actif, `RemoveAll` échoue.
- **Solution** : ne plus jamais éditer ce fichier via `containers://`. Éditer la source sur l'hôte, puis `docker compose restart wazuh.manager`. C'est aussi la bonne façon de versionner la règle dans Git.

### 11. Bind mount : éditer le mauvais fichier (chemin incohérent)
- **Symptôme** : `wazuh-analysisd -t` renvoie `(1103) Permission denied` sur `local_rules.xml`, alors que le fichier versionné est en 644 côté hôte et lisible via `cat` en root.
- **Cause** : le bind mount pointait vers `wazuh-siem/single-node/config/wazuh_cluster/local_rules.xml` (fichier d'origine du stack Wazuh), mais les `chmod`/`chown` étaient appliqués sur `wazuh/local_rules.xml` (copie versionnée, **non montée**). Le conteneur continuait à voir l'ancien fichier, en 660 owned par uid 1000, illisible pour wazuh (uid 999) via « others ».
- **Symptôme secondaire** : `docker compose.yml` sur disque ne contenait **pas** le bind (il avait été retiré ou n'avait jamais été commité), mais le conteneur l'avait toujours parce qu'il avait été créé à un moment où le compose le contenait. Un `restart` n'aurait jamais rechargé ce bind — seul `--force-recreate` le fait (ou l'inverse : un `--force-recreate` sans bind dans le compose l'aurait perdu).
- **Solution** :
  1. `chown eijv07:eijv07` + `chmod 644` sur `~/neobank-lab/wazuh/local_rules.xml`
  2. Ajouter au compose `wazuh.manager.volumes` : `/home/eijv07/neobank-lab/wazuh/local_rules.xml:/var/ossec/etc/rules/local_rules.xml`
  3. `docker compose up -d --force-recreate wazuh.manager`
  4. Vérifier via `docker inspect` que `Source` pointe vers le fichier versionné
- **Résultat** : une seule source de vérité (`wazuh/local_rules.xml` versionné dans le repo NeoBank), le compose reflète la réalité, plus de doublon à maintenir. Validé bout en bout : `curl` login raté → alerte `100100` dans `alerts.json` en <1s.