import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

import pyotp

BASE = "http://127.0.0.1:8080"
PWD = "MotDePasse123"


def new_user():
    name = "u" + uuid.uuid4().hex[:10]
    r = requests.post(f"{BASE}/accounts", json={"username": name, "password": PWD})
    assert r.status_code == 201
    return name


def login(name):
    r = requests.post(f"{BASE}/login", json={"username": name, "password": PWD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def credit(name, amount):
    # le nom est généré par les tests (hexadécimal), donc sûr dans cette commande
    sql = f"UPDATE accounts SET balance = {amount} WHERE username = '{name}';"
    subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "neobank", "-d", "neobank", "-c", sql],
        check=True, capture_output=True,
    )


def balance(headers):
    return requests.get(f"{BASE}/me", headers=headers).json()["balance"]


def transfer(headers, to, amount):
    return requests.post(f"{BASE}/transfers", headers=headers, json={"to_username": to, "amount": amount})


def test_duplicate_username_rejected():
    name = new_user()
    r = requests.post(f"{BASE}/accounts", json={"username": name, "password": PWD})
    assert r.status_code == 409


def test_short_password_rejected():
    r = requests.post(f"{BASE}/accounts", json={"username": "abc" + uuid.uuid4().hex[:6], "password": "court"})
    assert r.status_code == 422


def test_wrong_password_rejected():
    name = new_user()
    r = requests.post(f"{BASE}/login", json={"username": name, "password": "mauvais-mot-de-passe"})
    assert r.status_code == 401


def test_me_requires_token():
    assert requests.get(f"{BASE}/me").status_code in (401, 403)


def test_transfer_ok():
    a, b = new_user(), new_user()
    ha, hb = login(a), login(b)
    credit(a, 100)
    assert transfer(ha, b, "30.00").status_code == 201
    assert balance(ha) == "70.00"
    assert balance(hb) == "30.00"


def test_transfer_insufficient_funds():
    a, b = new_user(), new_user()
    ha = login(a)
    credit(a, 10)
    assert transfer(ha, b, "500.00").status_code == 400


def test_transfer_negative_amount_rejected():
    a, b = new_user(), new_user()
    assert transfer(login(a), b, "-5").status_code == 422


def test_transfer_to_self_rejected():
    a = new_user()
    assert transfer(login(a), a, "1.00").status_code == 400


def test_no_double_spend_under_concurrency():
    a, b = new_user(), new_user()
    ha = login(a)
    credit(a, 100)
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _: transfer(ha, b, "30.00").status_code, range(8)))
    assert codes.count(201) == 3  # 100 / 30 = 3 virements possibles, pas plus
    assert balance(ha) == "10.00"

def test_2fa_flow():
    name = new_user()
    h = login(name)
    secret = requests.post(f"{BASE}/2fa/setup", headers=h).json()["secret"]
    totp = pyotp.TOTP(secret)
    assert requests.post(f"{BASE}/2fa/enable", headers=h, json={"code": "000000"}).status_code == 400
    assert requests.post(f"{BASE}/2fa/enable", headers=h, json={"code": totp.now()}).status_code == 200
    creds = {"username": name, "password": PWD}
    assert requests.post(f"{BASE}/login", json=creds).status_code == 401
    assert requests.post(f"{BASE}/login", json={**creds, "otp": "000000"}).status_code == 401
    assert requests.post(f"{BASE}/login", json={**creds, "otp": totp.now()}).status_code == 200

def sql(query):
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "neobank", "-d", "neobank", "-t", "-A", "-c", query],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()

def test_audit_log_records_and_is_immutable():
    name = new_user()
    requests.post(f"{BASE}/login", json={"username": name, "password": "mauvais-mot-de-passe"})
    assert sql(f"SELECT count(*) FROM audit_log WHERE action='login_failed' AND details='{name}';") == "1"
    attempt = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "neobank", "-d", "neobank", "-c", "DELETE FROM audit_log;"],
        capture_output=True,
    )
    assert attempt.returncode != 0

def test_account_lockout_after_failed_logins():
    name = new_user()
    for _ in range(5):
        r = requests.post(f"{BASE}/login", json={"username": name, "password": "mauvais-mot-de-passe"})
        assert r.status_code == 401
    r = requests.post(f"{BASE}/login", json={"username": name, "password": PWD})
    assert r.status_code == 429

def user_id(headers):
    return requests.get(f"{BASE}/me", headers=headers).json()["id"]


def test_fraud_large_transfer_to_new_beneficiary_is_blocked():
    a, b = new_user(), new_user()
    ha = login(a)
    credit(a, 5000)
    assert transfer(ha, b, "1000.00").status_code == 403
    assert balance(ha) == "5000.00"
    assert sql(f"SELECT count(*) FROM audit_log WHERE action='transfer_blocked' AND user_id={user_id(ha)};") == "1"


def test_fraud_large_transfer_to_known_beneficiary_is_flagged_not_blocked():
    a, b = new_user(), new_user()
    ha = login(a)
    credit(a, 5000)
    assert transfer(ha, b, "100.00").status_code == 201
    assert transfer(ha, b, "1000.00").status_code == 201
    assert sql(f"SELECT count(*) FROM audit_log WHERE action='transfer_flagged' AND user_id={user_id(ha)};") == "1"