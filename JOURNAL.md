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