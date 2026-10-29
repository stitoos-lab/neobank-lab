import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field
import pyotp

import json

logger = logging.getLogger("neobank")

audit_file = logging.getLogger("neobank.audit")
audit_file.setLevel(logging.INFO)
audit_file.propagate = False
try:
    _handler = logging.FileHandler("/var/log/neobank/audit.log")
    _handler.setFormatter(logging.Formatter("%(message)s"))
    audit_file.addHandler(_handler)
except OSError:
    logger.warning("audit.log indisponible : journal fichier désactivé")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

#LES CONSTANTES 
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = "HS256"
JWT_TTL_MIN = 15
LOCK_MAX_FAILS = 5
FRAUD_BLOCK_SCORE = 60
FRAUD_FLAG_SCORE = 30
bearer = HTTPBearer()
# hash factice : même temps de réponse si l'utilisateur n'existe pas
DUMMY_HASH = pwd_context.hash("mot-de-passe-factice")


# requete parametre valide les entrée protection contre sql injection
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
    otp: str | None = Field(None, min_length=6, max_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class OtpCode(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


app = FastAPI(title="Neobank API")


def get_conn():
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=5,
    )

def audit(conn, action, user_id=None, ip=None, details=None):
    conn.execute(
        "INSERT INTO audit_log (user_id, action, ip, details) VALUES (%s, %s, %s, %s)",
        (user_id, action, ip, details),
    )
    audit_file.info(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "audit_action": action,
        "user_id": user_id,
        "srcip": ip,
        "details": details,
    }))

def fraud_score(conn, user_id, to_id, amount, balance):
    reasons = {}
    if amount >= 1000:
        reasons["montant_eleve"] = 40
    known = conn.execute(
        "SELECT 1 FROM transfers WHERE from_id = %s AND to_id = %s LIMIT 1",
        (user_id, to_id),
    ).fetchone()
    if not known and amount >= 500:
        reasons["nouveau_beneficiaire"] = 20
    recent = conn.execute(
        "SELECT count(*) FROM transfers WHERE from_id = %s AND created_at > now() - interval '10 minutes'",
        (user_id,),
    ).fetchone()[0]
    if recent >= 5:
        reasons["rafale"] = 40
    if amount >= 100 and amount >= balance * Decimal("0.9"):
        reasons["vidage_compte"] = 20
    return sum(reasons.values()), reasons

def client_ip(request: Request) -> str | None:
    return request.headers.get("x-real-ip")

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
def login(data: LoginRequest, request: Request):
    ip = client_ip(request)
    status, error, row = 401, None, None
    with get_conn() as conn:
        fails = conn.execute(
            "SELECT count(*) FROM audit_log "
            "WHERE action IN ('login_failed', 'login_failed_2fa') "
            "AND details = %s AND ts > now() - interval '15 minutes'",
            (data.username,),
        ).fetchone()[0]
        if fails >= LOCK_MAX_FAILS:
            audit(conn, "login_locked", None, ip, data.username)
            status, error = 429, "Trop de tentatives, réessayez plus tard"
        else:
            row = conn.execute(
                "SELECT id, hashed_password, totp_secret, totp_enabled FROM accounts WHERE username = %s",
                (data.username,),
            ).fetchone()
            valid = pwd_context.verify(data.password, row[1] if row else DUMMY_HASH)
            if not row or not valid:
                audit(conn, "login_failed", row[0] if row else None, ip, data.username)
                error = "Identifiants invalides"
            elif row[3] and not data.otp:
                error = "Code 2FA requis"
            elif row[3] and not pyotp.TOTP(row[2]).verify(data.otp, valid_window=1):
                audit(conn, "login_failed_2fa", row[0], ip, data.username)
                error = "Identifiants invalides"
            else:
                audit(conn, "login_ok", row[0], ip, data.username)
    if error:
        raise HTTPException(status_code=status, detail=error)
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
def transfer(data: TransferRequest, request: Request, user_id: int = Depends(current_user_id)):
    ip = client_ip(request)
    blocked = False
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
            score, reasons = fraud_score(conn, user_id, to_id, data.amount, balances[user_id])
            details = f"to={to_id} amount={data.amount} score={score} reasons={','.join(reasons)}"
            if score >= FRAUD_BLOCK_SCORE:
                audit(conn, "transfer_blocked", user_id, ip, details)
                blocked = True
            else:
                conn.execute("UPDATE accounts SET balance = balance - %s WHERE id = %s", (data.amount, user_id))
                conn.execute("UPDATE accounts SET balance = balance + %s WHERE id = %s", (data.amount, to_id))
                conn.execute(
                    "INSERT INTO transfers (from_id, to_id, amount) VALUES (%s, %s, %s)",
                    (user_id, to_id, data.amount),
                )
                action = "transfer_flagged" if score >= FRAUD_FLAG_SCORE else "transfer"
                audit(conn, action, user_id, ip, details)
    except psycopg.Error:
        logger.exception("Erreur lors du virement")
        raise HTTPException(status_code=500, detail="Erreur de base de données")
    if blocked:
        raise HTTPException(status_code=403, detail="Virement bloqué pour vérification")
    return {"status": "ok"}

@app.post("/2fa/setup")
def twofa_setup(user_id: int = Depends(current_user_id)):
    secret = pyotp.random_base32()
    with get_conn() as conn:
        row = conn.execute(
            "UPDATE accounts SET totp_secret = %s WHERE id = %s AND totp_enabled = FALSE RETURNING username",
            (secret, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="2FA déjà activée")
    uri = pyotp.TOTP(secret).provisioning_uri(name=row[0], issuer_name="NeoBank")
    return {"secret": secret, "otpauth_uri": uri}


@app.post("/2fa/enable")
def twofa_enable(data: OtpCode, user_id: int = Depends(current_user_id)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT totp_secret, totp_enabled FROM accounts WHERE id = %s", (user_id,)
        ).fetchone()
        if not row or not row[0] or row[1]:
            raise HTTPException(status_code=400, detail="Configuration 2FA invalide")
        if not pyotp.TOTP(row[0]).verify(data.code, valid_window=1):
            raise HTTPException(status_code=400, detail="Code invalide")
        conn.execute("UPDATE accounts SET totp_enabled = TRUE WHERE id = %s", (user_id,))
    return {"status": "2FA activée"}