import os

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from passlib.context import CryptContext
from psycopg.errors import UniqueViolation

# Context for hashing passwords
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

#modele pour valider les données entrées par l'utilisateur
#j'ai utilisé deux modèles pour contrer le problème de SQL injection
class AccountCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)

#modele pour formater les donnes de l'API
class AccountResponse(BaseModel):
    id: int
    username: str
    balance: float

app = FastAPI(title="Neobank API")

def get_conn():
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=5,
    )

@app.get("/health")
def health():
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok", "db": "ok"}

@app.post("/accounts", response_model=AccountResponse, status_code=201)
def create_account(account: AccountCreate):
    #je hash le mot de passe avant de l'enregistrer dans la base de données
    hashed_password = get_password_hash(account.password)

    try :
        with get_conn() as conn :
            with conn.cursor() as cur:
            #sql injection impossible grace a la parametrisation (%s)
                cur.execute(
                    """
                    INSERT INTO accounts (username, hashed_password)
                    VALUES (%s, %s)
                    RETURNING id, username, balance;
                    """,
                    (account.username, hashed_password)
                )
                new_account = cur.fetchone()

                #valider dans la base de données
                conn.commit()
                return {
                    "id": new_account[0],
                    "username": new_account[1],
                    "balance": float(new_account[2])
                }

    except UniqueViolation :
        raise HTTPException(status_code=400, detail="Ce nom d'utilisateur est déjà pris")
    except psycopg.Error as e:
        raise HTTPException(status_code=500, detail="Erreur de base de données")   