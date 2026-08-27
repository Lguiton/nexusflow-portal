"""
DATA-06: real coverage for backend/rate_limit.py's per-tenant ingestion
request-frequency limit, wired into POST /api/finance/upload-ledger in
backend/main.py. Hits the real HTTP endpoint (like test_api_endpoints.py's
upload tests) rather than calling check_ingestion_rate_limit directly, so
this also confirms the real wiring, not just the limiter function in
isolation.
"""
import io

import pytest

from backend import rate_limit


@pytest.fixture(autouse=True)
def _reset_rate_limit_state():
    """
    See rate_limit.reset_rate_limit_state_for_tests's own docstring for
    why this can't rely on the app/isolated_db fixtures' own per-test
    reset behavior -- this module's in-memory state needs its own,
    explicit clear. Runs before AND after each test in this file so an
    interrupted test can't leak state into the next one either.
    """
    rate_limit.reset_rate_limit_state_for_tests()
    yield
    rate_limit.reset_rate_limit_state_for_tests()


def _upload(client, auth_headers, seed: str):
    csv_content = f"date,category,amount,description\n2026-01-05,Sales,1000,{seed}\n".encode()
    return client.post(
        "/api/finance/upload-ledger",
        files={"file": (f"{seed}.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )


def test_uploads_under_the_limit_all_succeed(client, auth_headers):
    for i in range(rate_limit.MAX_INGEST_REQUESTS_PER_WINDOW):
        resp = _upload(client, auth_headers, f"under-limit-{i}")
        assert resp.status_code == 200, resp.text


def test_the_request_that_exceeds_the_limit_is_rejected_with_429(client, auth_headers):
    for i in range(rate_limit.MAX_INGEST_REQUESTS_PER_WINDOW):
        assert _upload(client, auth_headers, f"fill-{i}").status_code == 200

    over_limit = _upload(client, auth_headers, "one-too-many")
    assert over_limit.status_code == 429, over_limit.text
    assert "too many ledger uploads" in over_limit.json()["detail"].lower()


def test_a_rejected_429_does_not_itself_count_against_the_window(client, auth_headers):
    """Retrying immediately after a 429 must not push the tenant further
    into the hole -- only accepted attempts are recorded (see
    check_ingestion_rate_limit's own docstring)."""
    for i in range(rate_limit.MAX_INGEST_REQUESTS_PER_WINDOW):
        _upload(client, auth_headers, f"fill-{i}")

    first_429 = _upload(client, auth_headers, "over-1")
    second_429 = _upload(client, auth_headers, "over-2")
    assert first_429.status_code == 429
    assert second_429.status_code == 429
    # Same detail message both times -- neither call moved the window.
    assert first_429.json()["detail"] == second_429.json()["detail"]


def test_the_limit_is_scoped_per_tenant_not_global(client, auth_headers, make_auth_headers):
    for i in range(rate_limit.MAX_INGEST_REQUESTS_PER_WINDOW):
        assert _upload(client, auth_headers, f"tenant-a-{i}").status_code == 200
    assert _upload(client, auth_headers, "tenant-a-over").status_code == 429

    # A completely different tenant is unaffected -- its own window is
    # still empty.
    other_tenant_headers = make_auth_headers("OTHER-TENANT-CLI")
    resp = _upload(client, other_tenant_headers, "tenant-b-first")
    assert resp.status_code == 200, resp.text


def test_rate_limit_is_checked_before_any_file_is_actually_ingested(client, auth_headers):
    """A 429 must mean nothing was written -- confirmed by checking the
    ingestion history stays exactly at the number of ACCEPTED uploads."""
    for i in range(rate_limit.MAX_INGEST_REQUESTS_PER_WINDOW):
        _upload(client, auth_headers, f"fill-{i}")
    _upload(client, auth_headers, "rejected-attempt")

    history_resp = client.get(
        f"/api/v1/data/ingestion-history?limit={rate_limit.MAX_INGEST_REQUESTS_PER_WINDOW + 5}",
        headers=auth_headers,
    )
    assert history_resp.status_code == 200
    assert len(history_resp.json()["history"]) == rate_limit.MAX_INGEST_REQUESTS_PER_WINDOW
