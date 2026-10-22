import os

import psycopg
from fastapi import FastAPI, HTTPException

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