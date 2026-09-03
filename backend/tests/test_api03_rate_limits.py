"""
API-03: real coverage for backend/rate_limit.py's per-tenant burst,
per-source-IP burst, and per-tenant daily-quota limits, enforced globally
by main.py's enforce_api_rate_limits HTTP middleware. Hits real HTTP
endpoints through the `client` fixture (like test_ingestion_rate_limit.py
does for DATA-06) so this also confirms the real wiring -- middleware
registration order, exemptions, and the CORS/security-header interaction
-- not just the limiter functions in isolation.

The real limits (300/min per tenant, 60/min per IP, 20000/day per tenant)
are far too large to loop through in a fast test, so every test here
monkeypatches the specific constant(s) it needs down to a small value.
Each constant is read fresh from the module at call time (not bound as a
default argument -- see rate_limit.py's own module docstring), so
monkeypatch.setattr on the module attribute is sufficient.
"""
import pytest

from backend import rate_limit


def _signup(client, seed: str):
    email = f"{seed}@test.example"
    resp = client.post("/api/v1/auth/signup", json={
        "company_name": f"API-03 Test {seed}",
        "email": email,
        "password": "correct-horse-battery-staple",
    })
    assert resp.status_code == 200, resp.text
    return email


def test_health_endpoint_is_exempt_from_ip_rate_limiting(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "API_IP_BURST_LIMIT", 2)
    for _ in range(5):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200, resp.text


def test_a_non_exempt_unauthenticated_endpoint_hits_the_same_low_limit(client, monkeypatch):
    """Contrast case for the health-exemption test above: with the exact
    same tiny limit, an ordinary unauthenticated endpoint (login, with a
    nonexistent email so it stays a clean 401 up to the limit) DOES trip
    -- proving the health check's free pass above is a deliberate
    exemption, not evidence the limiter isn't really active."""
    monkeypatch.setattr(rate_limit, "API_IP_BURST_LIMIT", 2)
    for _ in range(2):
        resp = client.post("/api/v1/auth/login", json={"email": "nobody@test.example", "password": "x"})
        assert resp.status_code == 401, resp.text
    over_limit = client.post("/api/v1/auth/login", json={"email": "nobody@test.example", "password": "x"})
    assert over_limit.status_code == 429, over_limit.text
    assert "too many requests from this source" in over_limit.json()["detail"].lower()
    assert "Retry-After" in over_limit.headers


def test_ip_burst_limit_applies_across_different_emails_not_per_account(client, monkeypatch):
    """The real gap this item closes that AUTH-05's per-account lockout
    does not: AUTH-05 stops repeated wrong passwords against ONE email;
    nothing previously stopped one source trying a DIFFERENT email on
    every attempt. All of these unauthenticated login attempts must share
    ONE IP bucket regardless of which email each one names."""
    monkeypatch.setattr(rate_limit, "API_IP_BURST_LIMIT", 3)
    for i in range(3):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": f"nobody-{i}@test.example", "password": "x"},
        )
        assert resp.status_code == 401, resp.text

    over_limit = client.post(
        "/api/v1/auth/login",
        json={"email": "yet-another-nobody@test.example", "password": "x"},
    )
    assert over_limit.status_code == 429, over_limit.text


def test_tenant_burst_limit_trips_and_is_scoped_per_tenant_not_global(
    client, auth_headers, make_auth_headers, monkeypatch
):
    monkeypatch.setattr(rate_limit, "API_TENANT_BURST_LIMIT", 3)
    for _ in range(3):
        resp = client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200, resp.text

    over_limit = client.get("/api/v1/auth/me", headers=auth_headers)
    assert over_limit.status_code == 429, over_limit.text
    assert "too many requests for this account" in over_limit.json()["detail"].lower()

    # A completely different tenant is unaffected -- its own window is
    # still empty.
    other_tenant_headers = make_auth_headers("API03-OTHER-TENANT")
    resp = client.get("/api/v1/auth/me", headers=other_tenant_headers)
    assert resp.status_code == 200, resp.text


def test_a_rejected_429_does_not_itself_count_against_the_tenant_window(client, auth_headers, monkeypatch):
    monkeypatch.setattr(rate_limit, "API_TENANT_BURST_LIMIT", 2)
    for _ in range(2):
        client.get("/api/v1/auth/me", headers=auth_headers)

    first_429 = client.get("/api/v1/auth/me", headers=auth_headers)
    second_429 = client.get("/api/v1/auth/me", headers=auth_headers)
    assert first_429.status_code == 429
    assert second_429.status_code == 429
    assert first_429.json()["detail"] == second_429.json()["detail"]


def test_tenant_daily_quota_trips_independently_of_the_burst_window(client, auth_headers, monkeypatch):
    """A tenant can stay well under the per-minute burst limit and still
    be stopped by the separate daily ceiling -- burst limit deliberately
    left high here so only the quota path can be the one that trips."""
    monkeypatch.setattr(rate_limit, "API_TENANT_BURST_LIMIT", 1000)
    monkeypatch.setattr(rate_limit, "API_TENANT_DAILY_QUOTA", 3)
    for _ in range(3):
        resp = client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200, resp.text

    over_quota = client.get("/api/v1/auth/me", headers=auth_headers)
    assert over_quota.status_code == 429, over_quota.text
    assert "daily request quota reached" in over_quota.json()["detail"].lower()


def test_429_response_still_carries_security_headers(client, auth_headers, monkeypatch):
    """Confirms the deliberate middleware ordering in main.py: a 429
    produced by enforce_api_rate_limits still flows back out through
    add_security_headers, not just a normal 200."""
    monkeypatch.setattr(rate_limit, "API_TENANT_BURST_LIMIT", 1)
    client.get("/api/v1/auth/me", headers=auth_headers)
    over_limit = client.get("/api/v1/auth/me", headers=auth_headers)

    assert over_limit.status_code == 429
    assert over_limit.headers.get("X-Content-Type-Options") == "nosniff"
    assert over_limit.headers.get("X-Frame-Options") == "DENY"
    assert "Strict-Transport-Security" in over_limit.headers


def test_429_response_still_carries_cors_headers_for_an_allowed_origin(client, auth_headers, monkeypatch):
    """Confirms the other half of the deliberate middleware ordering: a
    429 still passes through CORSMiddleware. Without this, a real
    frontend's fetch() from an allowed origin would see an opaque CORS
    failure instead of a readable 429 status/body when rate-limited."""
    monkeypatch.setattr(rate_limit, "API_TENANT_BURST_LIMIT", 1)
    client.get("/api/v1/auth/me", headers=auth_headers)
    over_limit = client.get(
        "/api/v1/auth/me",
        headers={**auth_headers, "Origin": "http://localhost:3000"},
    )

    assert over_limit.status_code == 429
    assert over_limit.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_options_requests_are_never_rate_limited(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "API_IP_BURST_LIMIT", 1)
    for _ in range(5):
        resp = client.options("/api/v1/auth/me")
        assert resp.status_code != 429, resp.text
