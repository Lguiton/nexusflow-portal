"""
AUTH-02: real coverage for refresh-token rotation (backend/accounts.py's
refresh()/logout(), backend/db_manager.py's refresh_tokens storage). No
mocking -- these hit the real /api/v1/auth/{signup,login,refresh,logout}
endpoints against a real isolated DuckDB, the same way a real client
would.
"""
import jwt as pyjwt

from backend.accounts import TOKEN_TTL_MINUTES
from backend.auth import JWT_SECRET, JWT_ALGORITHM


def _signup(client, seed: str):
    email = f"{seed}@test.example"
    resp = client.post("/api/v1/auth/signup", json={
        "company_name": f"Refresh Test {seed}",
        "email": email,
        "password": "correct-horse-battery-staple",
    })
    assert resp.status_code == 200, resp.text
    return email, resp.json()


def test_signup_returns_both_a_short_lived_access_token_and_a_refresh_token(client):
    email, body = _signup(client, "refresh-signup-01")
    assert "access_token" in body and "refresh_token" in body
    assert body["access_token"] != body["refresh_token"]

    payload = pyjwt.decode(body["access_token"], JWT_SECRET, algorithms=[JWT_ALGORITHM])
    lifetime_seconds = payload["exp"] - payload["iat"]
    assert lifetime_seconds == TOKEN_TTL_MINUTES * 60


def test_login_returns_a_refresh_token(client):
    email, _ = _signup(client, "refresh-login-01")
    resp = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "refresh_token" in body and body["refresh_token"]


def test_refresh_with_a_valid_token_issues_a_new_working_access_token_and_rotates(client):
    _, signup_body = _signup(client, "refresh-rotate-01")
    old_refresh = signup_body["refresh_token"]

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] != signup_body["access_token"]
    assert body["refresh_token"] != old_refresh
    assert body["email"] == signup_body["email"]

    # The new access token actually works against a real protected endpoint.
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me_resp.status_code == 200, me_resp.text


def test_a_rotated_away_refresh_token_cannot_be_used_again(client):
    _, signup_body = _signup(client, "refresh-single-use-01")
    old_refresh = signup_body["refresh_token"]

    first = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert first.status_code == 200

    second = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert second.status_code == 401, second.text


def test_reusing_a_rotated_away_token_revokes_the_whole_chain(client):
    """
    The real security property: replaying an old (already-rotated) refresh
    token doesn't just fail itself -- it revokes every refresh token on
    the account, including the CURRENT, still-should-be-valid one, on the
    theory that a replay means the token chain was compromised.
    """
    _, signup_body = _signup(client, "refresh-chain-01")
    token_v1 = signup_body["refresh_token"]

    rotate_1 = client.post("/api/v1/auth/refresh", json={"refresh_token": token_v1})
    assert rotate_1.status_code == 200
    token_v2 = rotate_1.json()["refresh_token"]

    # Replay the RETIRED v1 token.
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": token_v1})
    assert replay.status_code == 401, replay.text
    assert "revoked" in replay.json()["detail"].lower()

    # The current, otherwise-still-valid v2 token is now ALSO dead.
    rotate_2 = client.post("/api/v1/auth/refresh", json={"refresh_token": token_v2})
    assert rotate_2.status_code == 401, rotate_2.text


def test_refresh_with_a_garbage_token_is_rejected(client):
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token-at-all"})
    assert resp.status_code == 401, resp.text


def test_logout_revokes_the_refresh_token_so_it_cannot_be_used_afterward(client):
    _, signup_body = _signup(client, "refresh-logout-01")
    refresh_token = signup_body["refresh_token"]

    logout_resp = client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_resp.status_code == 200, logout_resp.text
    assert logout_resp.json() == {"ok": True}

    # A logged-out token is REVOKED, not merely deleted -- the very next
    # refresh attempt with it must be treated as reuse (see the module
    # docstring in accounts.py's refresh()), i.e. still a clean 401.
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401, resp.text


def test_logout_is_idempotent_and_never_errors_on_a_missing_or_absent_token(client):
    resp1 = client.post("/api/v1/auth/logout", json={"refresh_token": "totally-made-up"})
    assert resp1.status_code == 200
    assert resp1.json() == {"ok": True}

    resp2 = client.post("/api/v1/auth/logout", json={})
    assert resp2.status_code == 200
    assert resp2.json() == {"ok": True}


def test_mfa_verify_also_returns_a_refresh_token(client):
    import pyotp

    email, signup_body = _signup(client, "refresh-mfa-01")
    headers = {"Authorization": f"Bearer {signup_body['access_token']}"}

    setup_resp = client.post("/api/v1/auth/mfa/setup", headers=headers)
    secret = setup_resp.json()["secret"]
    code = pyotp.TOTP(secret).now()
    enable_resp = client.post("/api/v1/auth/mfa/enable", json={"code": code}, headers=headers)
    assert enable_resp.status_code == 200, enable_resp.text

    login_resp = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    challenge_token = login_resp.json()["mfa_challenge_token"]
    code2 = pyotp.TOTP(secret).now()
    verify_resp = client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": code2},
        headers={"Authorization": f"Bearer {challenge_token}"},
    )
    assert verify_resp.status_code == 200, verify_resp.text
    assert "refresh_token" in verify_resp.json() and verify_resp.json()["refresh_token"]
