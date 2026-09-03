"""
OPS-05: real coverage for backend/status.py (maintenance-mode flag +
real DB-connectivity check) and its wiring into GET /api/v1/status and
main.py's enforce_api_rate_limits middleware (the real maintenance-mode
503 short-circuit).

Every test here points EIVANTA_MAINTENANCE_FLAG_PATH at a tmp_path file,
never the real backend/.maintenance_mode -- so no test can accidentally
leave the real, shared flag file in a dirty state for another test (or a
real operator) to trip over.
"""
import json
from pathlib import Path

import pytest

from backend import status as status_module


@pytest.fixture(autouse=True)
def _isolated_maintenance_flag(tmp_path, monkeypatch):
    """Every test in this file gets its own throwaway flag file path and
    starts with maintenance mode definitively OFF (env var cleared too)
    -- regardless of what any earlier test in the same process did."""
    flag_path = str(tmp_path / "maintenance_flag.json")
    monkeypatch.setenv("EIVANTA_MAINTENANCE_FLAG_PATH", flag_path)
    monkeypatch.delenv("EIVANTA_MAINTENANCE_MODE", raising=False)
    return flag_path


# ---------------------------------------------------------------------
# backend/status.py directly
# ---------------------------------------------------------------------

def test_maintenance_mode_defaults_to_off():
    assert status_module.is_maintenance_mode() is False
    assert status_module.get_maintenance_status() == {"active": False, "reason": None, "since": None}


def test_enable_and_disable_via_flag_file():
    status_module.enable_maintenance_mode(reason="Scheduled DB migration")
    assert status_module.is_maintenance_mode() is True
    info = status_module.get_maintenance_status()
    assert info["active"] is True
    assert info["reason"] == "Scheduled DB migration"
    assert info["since"]  # a real, non-empty ISO timestamp was recorded

    status_module.disable_maintenance_mode()
    assert status_module.is_maintenance_mode() is False


def test_env_var_trigger_works_independently_of_the_flag_file(monkeypatch):
    monkeypatch.setenv("EIVANTA_MAINTENANCE_MODE", "true")
    assert status_module.is_maintenance_mode() is True
    # No flag file was ever created -- get_maintenance_status still
    # correctly reports active, just without reason/since metadata
    # (the env trigger carries none of its own).
    info = status_module.get_maintenance_status()
    assert info == {"active": True, "reason": None, "since": None}


@pytest.mark.parametrize("value", ["1", "true", "True", "YES", "on"])
def test_env_var_true_ish_values_all_trigger_maintenance(monkeypatch, value):
    monkeypatch.setenv("EIVANTA_MAINTENANCE_MODE", value)
    assert status_module.is_maintenance_mode() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_env_var_false_ish_values_do_not_trigger_maintenance(monkeypatch, value):
    monkeypatch.setenv("EIVANTA_MAINTENANCE_MODE", value)
    assert status_module.is_maintenance_mode() is False


def test_an_unreadable_flag_file_still_counts_as_active(_isolated_maintenance_flag):
    """Fails toward the SAFER state (see status.py's own docstring): a
    corrupt/unparseable flag file must never silently be treated as
    'maintenance is off'."""
    Path(_isolated_maintenance_flag).write_text("not valid json {{{")
    assert status_module.is_maintenance_mode() is True
    info = status_module.get_maintenance_status()
    assert info["active"] is True
    assert info["reason"] is None  # unparseable, so no metadata recovered -- but still active


def test_check_db_reachable_true_against_a_real_isolated_db(isolated_db):
    import asyncio
    assert asyncio.run(status_module.check_db_reachable()) is True


def test_check_db_reachable_false_against_an_impossible_path(isolated_db, monkeypatch):
    import asyncio
    # A path inside a directory that doesn't exist -- duckdb.connect
    # cannot create it, so this is a real, unrecoverable connection
    # failure, not just "the file doesn't exist yet" (which duckdb
    # auto-creates and would still count as reachable).
    monkeypatch.setattr(isolated_db, "DB_PATH", "/this/directory/does/not/exist/at/all/x.duckdb")
    assert asyncio.run(status_module.check_db_reachable()) is False


# ---------------------------------------------------------------------
# GET /api/v1/status
# ---------------------------------------------------------------------

def test_status_endpoint_reports_operational_by_default(client):
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_status"] == "operational"
    assert body["database_reachable"] is True
    assert body["maintenance"]["active"] is False
    assert body["checked_at"]


def test_status_endpoint_is_public_no_auth_required(client):
    resp = client.get("/api/v1/status")
    assert resp.status_code != 401
    assert resp.status_code != 403


def test_status_endpoint_reports_maintenance_when_active(client):
    status_module.enable_maintenance_mode(reason="Testing")
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_status"] == "maintenance"
    assert body["maintenance"]["active"] is True
    assert body["maintenance"]["reason"] == "Testing"


def test_status_endpoint_reports_degraded_when_db_unreachable(client, isolated_db, monkeypatch):
    monkeypatch.setattr(isolated_db, "DB_PATH", "/this/directory/does/not/exist/at/all/x.duckdb")
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_status"] == "degraded"
    assert body["database_reachable"] is False


def test_maintenance_status_takes_precedence_over_a_degraded_db(client, isolated_db, monkeypatch):
    """A declared maintenance window is reported as-is even if the DB
    also happens to be unreachable right now -- an operator who put the
    platform in maintenance already knows why; the reported status
    should say MAINTENANCE, not confusingly downgrade to DEGRADED."""
    monkeypatch.setattr(isolated_db, "DB_PATH", "/this/directory/does/not/exist/at/all/x.duckdb")
    status_module.enable_maintenance_mode(reason="DB migration in progress")
    resp = client.get("/api/v1/status")
    body = resp.json()
    assert body["overall_status"] == "maintenance"
    assert body["database_reachable"] is False  # still reported honestly underneath


# ---------------------------------------------------------------------
# Maintenance mode's real effect on every OTHER endpoint
# ---------------------------------------------------------------------

def test_maintenance_mode_returns_503_for_a_real_protected_endpoint(client, auth_headers):
    status_module.enable_maintenance_mode(reason="Testing")
    resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert "maintenance" in body["detail"].lower()
    assert body["maintenance"]["reason"] == "Testing"
    assert resp.headers.get("Retry-After") == "300"


def test_maintenance_mode_returns_503_for_unauthenticated_requests_too(client):
    status_module.enable_maintenance_mode()
    resp = client.post("/api/v1/auth/login", json={"email": "nobody@test.example", "password": "x"})
    assert resp.status_code == 503, resp.text


def test_health_and_status_endpoints_stay_reachable_during_maintenance(client):
    status_module.enable_maintenance_mode(reason="Testing")
    health = client.get("/api/v1/health")
    stat = client.get("/api/v1/status")
    assert health.status_code == 200
    assert stat.status_code == 200
    assert stat.json()["overall_status"] == "maintenance"


def test_maintenance_response_still_carries_security_and_cors_headers(client, auth_headers):
    """Same deliberate middleware-ordering guarantee API-03's own 429
    tests already confirm for rate-limit responses -- a maintenance 503
    must flow back out through add_security_headers and CORSMiddleware
    too, not just a normal 200."""
    status_module.enable_maintenance_mode()
    resp = client.get(
        "/api/v1/auth/me",
        headers={**auth_headers, "Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 503
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_options_requests_are_never_blocked_by_maintenance_mode(client):
    status_module.enable_maintenance_mode()
    resp = client.options("/api/v1/auth/me")
    assert resp.status_code != 503


def test_maintenance_mode_short_circuits_before_rate_limit_bookkeeping(client, auth_headers, monkeypatch):
    """A request rejected for maintenance must not itself consume the
    tenant's rate-limit budget -- confirmed by tripping a tiny burst
    limit AFTER a maintenance-mode request, and observing it still
    takes the full limit's worth of real requests to trip, not one
    fewer."""
    from backend import rate_limit
    monkeypatch.setattr(rate_limit, "API_TENANT_BURST_LIMIT", 2)

    status_module.enable_maintenance_mode()
    maintenance_resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert maintenance_resp.status_code == 503

    status_module.disable_maintenance_mode()
    first = client.get("/api/v1/auth/me", headers=auth_headers)
    second = client.get("/api/v1/auth/me", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text  # would be 429 already if maintenance had consumed a slot

    third = client.get("/api/v1/auth/me", headers=auth_headers)
    assert third.status_code == 429, third.text


def test_disabling_maintenance_mode_restores_normal_service(client, auth_headers):
    status_module.enable_maintenance_mode()
    assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 503

    status_module.disable_maintenance_mode()
    assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 200
