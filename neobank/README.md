# NeoBANK API

API bancaire fictive : FastAPI, PostgreSQL, nginx, segementée en trois zones Docker('dmz', 'app', 'data').
## Endpoints
| Méthode | Route | Rôle |
| --- | --- | --- |
| POST | /accounts | Création de compte |
| POST | /login | Connexion, renvoie un jeton JWT (15 min) |
| GET | /me | Compte de l'utilisateur connecté |
| POST | /transfers | Virement atomique entre comptes |
## Choix de sécurité
- Mots de passe hachés avec bcrypt, jamais renvoyés.
- Requêtes SQL paramétrées contre l'injection.
- Montants en `Decimal`, jamais en `float`.
- Expéditeur du virement tiré du jeton, pas de la requête.
- Virement dans une transaction avec verrou `FOR UPDATE` : pas de double dépense.
- Contrainte SQL `balance >= 0` en dernier rempart.
- Messages de connexion identiques (pas d'énumération de comptes), hash factice pour égaliser les temps de réponse.
- Secrets dans `.env`, hors du dépôt.

## Tests
`python -m pytest tests -v` (le lab Docker doit tourner).
