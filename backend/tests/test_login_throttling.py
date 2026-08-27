"""
AUTH-05: real coverage for login brute-force throttling (backend/accounts.py's
login() + backend/db_manager.py's record_failed_login/update_last_login).
No mocking of the lockout logic itself -- these hit the real
/api/v1/auth/login endpoint against the real isolated DuckDB, the same way
a real client would.
"""
from datetime import datetime, timedelta, timezone

import duckdb

from backend.accounts import MAX_FAILED_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_MINUTES


def _signup(client, client_id_seed: str):
    email = f"{client_id_seed}@test.example"
    resp = client.post("/api/v1/auth/signup", json={
        "company_name": f"Throttle Test {client_id_seed}",
        "email": email,
        "password": "correct-horse-battery-staple",
    })
    assert resp.status_code == 200, resp.text
    return email


def test_wrong_password_below_threshold_stays_401(client):
    email = _signup(client, "throttle-01")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 1):
        resp = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
        assert resp.status_code == 401
    # Still not locked -- one attempt short of the threshold.
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-staple"})
    assert resp.status_code == 200, resp.text


def test_threshold_failures_lock_the_account(client):
    email = _signup(client, "throttle-02")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        resp = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    # The attempt that CROSSES the threshold gets told immediately, not a
    # generic 401 followed by a surprise lock on the next try.
    assert resp.status_code == 429, resp.text
    assert "too many" in resp.json()["detail"].lower()


def test_locked_account_rejects_even_the_correct_password(client):
    email = _signup(client, "throttle-03")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-staple"})
    assert resp.status_code == 429, resp.text


def test_successful_login_resets_the_counter(client):
    email = _signup(client, "throttle-04")
    # Fail a few times, but stay under the threshold.
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 2):
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    # A real successful login should zero the counter out.
    good = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-staple"})
    assert good.status_code == 200, good.text
    # Now fail almost up to the threshold again -- if the counter hadn't
    # reset, these plus the earlier failures would already exceed it.
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 1):
        resp = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
        assert resp.status_code == 401, "should not be locked yet -- counter should have reset on the earlier success"


def test_nonexistent_email_never_locks_or_leaks_existence(client, isolated_db):
    # No signup for this email at all. It should behave identically to a
    # wrong password every single time -- never 429, never distinguishable
    # from throttle-05-real@test.example existing but having a bad password.
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS + 3):
        resp = client.post("/api/v1/auth/login", json={"email": "nobody-throttle-05@test.example", "password": "wrong"})
        assert resp.status_code == 401
    # And confirm there's genuinely no row to have locked in the first place.
    user = duckdb.connect(isolated_db.DB_PATH).execute(
        "SELECT 1 FROM users WHERE email = ?", ["nobody-throttle-05@test.example"]
    ).fetchone()
    assert user is None


def test_lockout_expires_after_the_window(client, isolated_db):
    email = _signup(client, "throttle-06")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    # Confirm it's actually locked first.
    locked_resp = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-staple"})
    assert locked_resp.status_code == 429

    # Directly move locked_until into the past -- the real code path
    # (record_failed_login) sets a real future timestamp; this simulates
    # real wall-clock time passing without an actual 15-minute sleep in
    # the test suite. Same "reach into the isolated DB directly" pattern
    # already used elsewhere in this suite for direct state verification.
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    conn = duckdb.connect(isolated_db.DB_PATH)
    conn.execute("UPDATE users SET locked_until = ? WHERE email = ?", [past, email])
    conn.close()

    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-staple"})
    assert resp.status_code == 200, resp.text


def test_login_rejects_missing_fields(client):
    resp = client.post("/api/v1/auth/login", json={})
    assert resp.status_code == 422
