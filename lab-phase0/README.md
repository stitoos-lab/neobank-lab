# Lab phase à : réseau Docker isolé

Deux conteneurs sur un réseau 'labnet' :

-'web' (nginx) : publié sur '127.0.0.1:8080' uniquement.
- 'db' (PostgreSQL) : aucun port publié, joignable seulement depuis 'web'.

## Vérification 

- 'docker compose exec web ping -c 2 db' : 'web' joint 'db' par son nom.
- 'python3 ../scanner.py 127.0.0.1 -p 8080,5432' : 8080 ouvert, 5432 fermé.

Conclusion : la base pour l'application fonctionne mais n'est pas exposée.
