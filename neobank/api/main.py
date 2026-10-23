import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

logger = logging.getLogger("neobank")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = "HS256"
JWT_TTL_MIN = 15
bearer = HTTPBearer()
# hash factice : même temps de réponse si l'utilisateur n'existe pas
DUMMY_HASH = pwd_context.hash("mot-de-passe-factice")


# Pydantic valide les entrées. La protection contre l'injection SQL vient
# des requêtes paramétrées (%s), pas des modèles.
class AccountCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=72)


class AccountResponse(BaseModel):
    id: int
    username: str
    balance: Decimal


class LoginRequest(BaseModel):
    username: str
    password: str = Field(..., max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


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
    hashed_password = pwd_context.hash(account.password)
    try:
        with get_conn() as conn:
            row = conn.execute(
                """
                INSERT INTO accounts (username, hashed_password)
                VALUES (%s, %s)
                RETURNING id, username, balance;
                """,
                (account.username, hashed_password),
            ).fetchone()
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="Ce nom d'utilisateur est déjà pris")
    except psycopg.Error:
        logger.exception("Erreur lors de la création du compte")
        raise HTTPException(status_code=500, detail="Erreur de base de données")
    return {"id": row[0], "username": row[1], "balance": row[2]}


@app.post("/login", response_model=TokenResponse)
def login(data: LoginRequest):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, hashed_password FROM accounts WHERE username = %s",
            (data.username,),
        ).fetchone()
    valid = pwd_context.verify(data.password, row[1] if row else DUMMY_HASH)
    if not row or not valid:
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(row[0]), "iat": now, "exp": now + timedelta(minutes=JWT_TTL_MIN)},
        JWT_SECRET,
        algorithm=JWT_ALGO,
    )
    return {"access_token": token}


def current_user_id(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> int:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Jeton invalide ou expiré")
    return int(payload["sub"])


@app.get("/me", response_model=AccountResponse)
def me(user_id: int = Depends(current_user_id)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, balance FROM accounts WHERE id = %s", (user_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Compte introuvable")
    return {"id": row[0], "username": row[1], "balance": row[2]}

class TransferRequest(BaseModel):
    to_username: str
    amount: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)


@app.post("/transfers", status_code=201)
def transfer(data: TransferRequest, user_id: int = Depends(current_user_id)):
    try:
        with get_conn() as conn:
                dest = conn.execute(
                    "SELECT id FROM accounts WHERE username = %s", (data.to_username,)
                ).fetchone()
                if not dest:
                    raise HTTPException(status_code=404, detail="Destinataire introuvable")
                to_id = dest[0]
                if to_id == user_id:
                    raise HTTPException(status_code=400, detail="Virement vers soi-même impossible")
                # verrou dans l'ordre des id pour éviter les blocages croisés
                rows = conn.execute(
                    "SELECT id, balance FROM accounts WHERE id IN (%s, %s) ORDER BY id FOR UPDATE",
                    (user_id, to_id),
                ).fetchall()
                balances = {r[0]: r[1] for r in rows}
                if balances[user_id] < data.amount:
                    raise HTTPException(status_code=400, detail="Solde insuffisant")
                conn.execute("UPDATE accounts SET balance = balance - %s WHERE id = %s", (data.amount, user_id))
                conn.execute("UPDATE accounts SET balance = balance + %s WHERE id = %s", (data.amount, to_id))
                conn.execute(
                    "INSERT INTO transfers (from_id, to_id, amount) VALUES (%s, %s, %s)",
                    (user_id, to_id, data.amount),
                )
    except psycopg.Error:
        logger.exception("Erreur lors du virement")
        raise HTTPException(status_code=500, detail="Erreur de base de données")
    return {"status": "ok"}