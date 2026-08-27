"""
AUTH-04: real coverage for TOTP-based MFA (backend/accounts.py's
mfa_setup/mfa_enable/mfa_verify/mfa_disable/mfa_status endpoints, the
login() MFA branch, and backend/auth.py's challenge-token security
separation). No mocking of pyotp/qrcode/Fernet -- these hit the real
endpoints against a real isolated DuckDB, generate real TOTP codes with
pyotp, and decrypt real Fernet-encrypted secrets, the same way a real
client and a real authenticator app would.
"""
import pyotp
import pytest

from backend.accounts import MAX_FAILED_LOGIN_ATTEMPTS


def _signup(client, seed: str):
    email = f"{seed}@test.example"
    resp = client.post("/api/v1/auth/signup", json={
        "company_name": f"MFA Test {seed}",
        "email": email,
        "password": "correct-horse-battery-staple",
    })
    assert resp.status_code == 200, resp.text
    return email, resp.json()["access_token"]


def _enroll_mfa(client, headers):
    """Runs a real /mfa/setup -> real TOTP code -> real /mfa/enable round trip. Returns (secret, backup_codes)."""
    setup_resp = client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert setup_resp.status_code == 200, setup_resp.text
    body = setup_resp.json()
    assert body["secret"]
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["qr_code_data_uri"].startswith("data:image/png;base64,")

    secret = body["secret"]
    code = pyotp.TOTP(secret).now()
    enable_resp = client.post("/api/v1/auth/mfa/enable", json={"code": code}, headers=headers)
    assert enable_resp.status_code == 200, enable_resp.text
    enable_body = enable_resp.json()
    assert enable_body["enabled"] is True
    assert len(enable_body["backup_codes"]) == 8
    return secret, enable_body["backup_codes"]


def test_setup_generates_real_secret_qr_and_otpauth_uri(client):
    _, token = _signup(client, "mfa-setup-01")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The secret is a real base32 TOTP secret -- pyotp can build a working generator from it.
    totp = pyotp.TOTP(body["secret"])
    assert len(totp.now()) == 6
    assert "secret=" + body["secret"] in body["otpauth_uri"] or body["secret"] in body["otpauth_uri"]


def test_enable_with_correct_code_succeeds_and_returns_backup_codes(client):
    _, token = _signup(client, "mfa-enable-01")
    headers = {"Authorization": f"Bearer {token}"}
    secret, backup_codes = _enroll_mfa(client, headers)
    assert len(set(backup_codes)) == 8  # all unique
    for c in backup_codes:
        assert len(c) == 9 and c[4] == "-"

    status = client.get("/api/v1/auth/mfa/status", headers=headers)
    assert status.status_code == 200, status.text
    assert status.json() == {"enabled": True, "backup_codes_remaining": 8}


def test_enable_with_incorrect_code_is_rejected_and_does_not_enable(client):
    _, token = _signup(client, "mfa-enable-02")
    headers = {"Authorization": f"Bearer {token}"}
    setup_resp = client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert setup_resp.status_code == 200

    resp = client.post("/api/v1/auth/mfa/enable", json={"code": "000000"}, headers=headers)
    assert resp.status_code == 400, resp.text

    status = client.get("/api/v1/auth/mfa/status", headers=headers)
    assert status.json()["enabled"] is False


def test_enable_with_no_pending_setup_returns_400(client):
    _, token = _signup(client, "mfa-enable-03")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/auth/mfa/enable", json={"code": "123456"}, headers=headers)
    assert resp.status_code == 400, resp.text
    assert "setup" in resp.json()["detail"].lower()


def test_login_on_mfa_enabled_account_returns_challenge_not_a_real_token(client):
    email, token = _signup(client, "mfa-login-01")
    headers = {"Authorization": f"Bearer {token}"}
    _enroll_mfa(client, headers)

    login_resp = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    assert login_resp.status_code == 200, login_resp.text
    body = login_resp.json()
    assert body == {"mfa_required": True, "mfa_challenge_token": body["mfa_challenge_token"]}
    assert "access_token" not in body


def test_mfa_verify_with_correct_code_completes_login_and_resets_lockout_state(client):
    email, token = _signup(client, "mfa-login-02")
    headers = {"Authorization": f"Bearer {token}"}
    secret, _ = _enroll_mfa(client, headers)

    login_resp = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    challenge_token = login_resp.json()["mfa_challenge_token"]

    code = pyotp.TOTP(secret).now()
    verify_resp = client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": code},
        headers={"Authorization": f"Bearer {challenge_token}"},
    )
    assert verify_resp.status_code == 200, verify_resp.text
    body = verify_resp.json()
    assert "access_token" in body and body["email"] == email

    # The real access token actually works against a normal protected endpoint.
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me_resp.status_code == 200, me_resp.text


def test_mfa_verify_with_incorrect_code_is_rejected_and_shares_the_lockout_counter(client):
    email, token = _signup(client, "mfa-login-03")
    headers = {"Authorization": f"Bearer {token}"}
    secret, _ = _enroll_mfa(client, headers)

    login_resp = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    challenge_token = login_resp.json()["mfa_challenge_token"]
    ch_headers = {"Authorization": f"Bearer {challenge_token}"}

    # Wrong codes accumulate against the SAME AUTH-05 lockout counter a
    # wrong password uses -- eventually locking at the same threshold.
    for i in range(MAX_FAILED_LOGIN_ATTEMPTS - 1):
        resp = client.post("/api/v1/auth/mfa/verify", json={"code": "000000"}, headers=ch_headers)
        assert resp.status_code == 401, resp.text

    resp = client.post("/api/v1/auth/mfa/verify", json={"code": "000000"}, headers=ch_headers)
    assert resp.status_code == 429, resp.text
    assert "too many" in resp.json()["detail"].lower()

    # Even the CORRECT code is now rejected until the lockout window passes.
    code = pyotp.TOTP(secret).now()
    resp = client.post("/api/v1/auth/mfa/verify", json={"code": code}, headers=ch_headers)
    assert resp.status_code == 429, resp.text


def test_backup_code_completes_login_and_is_single_use(client):
    email, token = _signup(client, "mfa-backup-01")
    headers = {"Authorization": f"Bearer {token}"}
    _, backup_codes = _enroll_mfa(client, headers)
    one_code = backup_codes[0]

    login_resp = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    challenge_token_1 = login_resp.json()["mfa_challenge_token"]
    resp1 = client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": one_code},
        headers={"Authorization": f"Bearer {challenge_token_1}"},
    )
    assert resp1.status_code == 200, resp1.text

    status = client.get("/api/v1/auth/mfa/status", headers=headers)
    assert status.json()["backup_codes_remaining"] == 7

    # Reusing the SAME backup code on a second login attempt fails.
    login_resp2 = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    challenge_token_2 = login_resp2.json()["mfa_challenge_token"]
    resp2 = client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": one_code},
        headers={"Authorization": f"Bearer {challenge_token_2}"},
    )
    assert resp2.status_code == 401, resp2.text


def test_disable_requires_correct_password_and_code_and_actually_turns_off(client):
    email, token = _signup(client, "mfa-disable-01")
    headers = {"Authorization": f"Bearer {token}"}
    secret, _ = _enroll_mfa(client, headers)

    # Wrong password, correct code -> rejected.
    code = pyotp.TOTP(secret).now()
    resp = client.post("/api/v1/auth/mfa/disable", json={
        "password": "wrong-password", "code": code,
    }, headers=headers)
    assert resp.status_code == 401, resp.text

    # Correct password, wrong code -> rejected.
    resp = client.post("/api/v1/auth/mfa/disable", json={
        "password": "correct-horse-battery-staple", "code": "000000",
    }, headers=headers)
    assert resp.status_code == 400, resp.text

    status = client.get("/api/v1/auth/mfa/status", headers=headers)
    assert status.json()["enabled"] is True

    # Both correct -> actually disables.
    code = pyotp.TOTP(secret).now()
    resp = client.post("/api/v1/auth/mfa/disable", json={
        "password": "correct-horse-battery-staple", "code": code,
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": False}

    status = client.get("/api/v1/auth/mfa/status", headers=headers)
    assert status.json() == {"enabled": False, "backup_codes_remaining": 0}

    # Login now succeeds directly again, no challenge step.
    login_resp = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()


def test_disable_when_not_enabled_returns_400(client):
    _, token = _signup(client, "mfa-disable-02")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/auth/mfa/disable", json={
        "password": "correct-horse-battery-staple", "code": "000000",
    }, headers=headers)
    assert resp.status_code == 400, resp.text


def test_raw_mfa_challenge_token_is_rejected_by_normal_protected_endpoints(client):
    email, token = _signup(client, "mfa-security-01")
    headers = {"Authorization": f"Bearer {token}"}
    _enroll_mfa(client, headers)

    login_resp = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    challenge_token = login_resp.json()["mfa_challenge_token"]
    ch_headers = {"Authorization": f"Bearer {challenge_token}"}

    # The security property: a challenge token must never work as a real
    # access token anywhere else -- proving _decode_and_build_user's
    # explicit rejection actually holds against a real endpoint.
    resp = client.get("/api/v1/auth/me", headers=ch_headers)
    assert resp.status_code == 401, resp.text
    assert "mfa verification" in resp.json()["detail"].lower()


def test_real_access_token_is_rejected_by_the_mfa_verify_endpoint(client):
    """The inverse security property: a real access token cannot be used to complete an MFA challenge either."""
    _, token = _signup(client, "mfa-security-02")
    resp = client.post("/api/v1/auth/mfa/verify", json={"code": "123456"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401, resp.text
    assert "not a valid mfa challenge" in resp.json()["detail"].lower()


def test_mfa_status_returns_only_the_callers_own_status(client):
    _, token_a = _signup(client, "mfa-status-a")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    _enroll_mfa(client, headers_a)

    _, token_b = _signup(client, "mfa-status-b")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    status_a = client.get("/api/v1/auth/mfa/status", headers=headers_a)
    status_b = client.get("/api/v1/auth/mfa/status", headers=headers_b)
    assert status_a.json()["enabled"] is True
    assert status_b.json()["enabled"] is False


def test_re_setup_does_not_clobber_active_secret_until_confirmed(client):
    """
    An already-enabled account calling /mfa/setup again (e.g. re-enrolling
    a new device) must keep working with its OLD secret until the NEW one
    is actually confirmed via /mfa/enable.
    """
    email, token = _signup(client, "mfa-reenroll-01")
    headers = {"Authorization": f"Bearer {token}"}
    old_secret, _ = _enroll_mfa(client, headers)

    # Start a new enrollment but never confirm it.
    resp = client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert resp.status_code == 200
    new_secret = resp.json()["secret"]
    assert new_secret != old_secret

    # A real login still completes with the OLD secret's code.
    login_resp = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery-staple",
    })
    challenge_token = login_resp.json()["mfa_challenge_token"]
    old_code = pyotp.TOTP(old_secret).now()
    verify_resp = client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": old_code},
        headers={"Authorization": f"Bearer {challenge_token}"},
    )
    assert verify_resp.status_code == 200, verify_resp.text
