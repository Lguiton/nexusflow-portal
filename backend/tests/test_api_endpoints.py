"""
Real FastAPI TestClient tests for the HTTP layer -- auth enforcement,
status codes, and end-to-end request/response shape for every endpoint in
main.py that does NOT require a real OpenAI call (those are excluded here;
see test_agent_endpoints_require_auth.py for the auth-gate-only coverage
of that group).
"""
import io

import pytest


def test_health_endpoint(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ONLINE"


def test_dev_login_issues_real_jwt(client):
    resp = client.post("/api/v1/auth/dev-login", json={"client_id": "CLI-042"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_id"] == "CLI-042"
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20


def test_dev_login_sanitizes_client_id(client):
    resp = client.post("/api/v1/auth/dev-login", json={"client_id": "CLI 001!!!<script>"})
    assert resp.status_code == 200
    # sanitize_client_id strips anything outside [A-Za-z0-9_-]
    assert resp.json()["client_id"] == "CLI001script"


@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/data/ingestion-history"),
    ("delete", "/api/v1/finance/ledger"),
    ("post", "/api/v1/finance/kpi-summary"),
    ("post", "/api/v1/finance/analytics-summary"),
    ("get", "/api/v1/assumptions"),
    ("post", "/api/v1/insights/known-gaps"),
    ("post", "/api/v1/finance/ledger-rows"),
    ("post", "/api/v1/data/category-suggestions"),
    ("get", "/api/v1/metrics/ingestion"),
    ("get", "/api/v1/metrics/swarm"),
    ("get", "/api/v1/metrics/ai-usage"),
])
def test_protected_endpoints_reject_missing_auth(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 401, f"{method.upper()} {path} should require auth, got {resp.status_code}"


def test_protected_endpoint_rejects_garbage_token(client):
    resp = client.get("/api/v1/assumptions", headers={"Authorization": "Bearer not.a.real.jwt"})
    assert resp.status_code == 401


def test_upload_ledger_end_to_end(client, auth_headers):
    csv_content = b"date,category,amount,description\n2026-01-05,Sales,1000,Widget sale\n"
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("ledger.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"
    assert "Successfully ingested 1 records" in resp.json()["message"]


def test_upload_ledger_rejects_bad_file_with_400_not_500(client, auth_headers):
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_upload_then_ingestion_history_shows_it(client, auth_headers):
    csv_content = b"date,category,amount,description\n2026-01-05,Sales,1000,Widget sale\n"
    client.post(
        "/api/finance/upload-ledger",
        files={"file": ("history_test.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    resp = client.get("/api/v1/data/ingestion-history", headers=auth_headers)
    assert resp.status_code == 200
    history = resp.json()["history"]
    assert any(h["filename"] == "history_test.csv" and h["status"] == "SUCCESS" for h in history)


def test_upload_then_delete_ledger(client, auth_headers):
    csv_content = b"date,category,amount,description\n2026-01-05,Sales,1000,Widget sale\n"
    client.post(
        "/api/finance/upload-ledger",
        files={"file": ("to_delete.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    resp = client.delete("/api/v1/finance/ledger", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SUCCESS"
    assert body["rows_deleted"] == 1

    # Second delete on an already-empty ledger is a real 0, not an error.
    resp2 = client.delete("/api/v1/finance/ledger", headers=auth_headers)
    assert resp2.status_code == 200
    assert resp2.json()["rows_deleted"] == 0


def test_analytics_summary_no_data_state(client, auth_headers):
    resp = client.post("/api/v1/finance/analytics-summary", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "NO_DATA"


def test_analytics_summary_computed_from_real_ledger(client, auth_headers):
    csv_content = (
        b"date,category,amount,description\n"
        b"2026-01-05,Sales,1000,Revenue row\n"
        b"2026-01-06,Rent,-300,Expense row\n"
    )
    client.post(
        "/api/finance/upload-ledger",
        files={"file": ("analytics.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    resp = client.post("/api/v1/finance/analytics-summary", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert body["total_revenue"] == pytest.approx(1000.0)
    assert body["total_expense"] == pytest.approx(300.0)
    assert body["net_profit"] == pytest.approx(700.0)


def test_kpi_summary_shape(client, auth_headers):
    resp = client.post("/api/v1/finance/kpi-summary", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    for key in ("ledger_total_amount", "ledger_row_count", "mrr", "mrr_available", "mrr_note"):
        assert key in body


def test_assumptions_endpoint_reflects_live_module_constants(client, auth_headers):
    from backend.agents import virtual_cfo, predictive_forecaster

    resp = client.get("/api/v1/assumptions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    by_key = {a["key"]: a["value"] for a in body["numeric_assumptions"]}
    assert by_key["assumed_cash_reserves"] == virtual_cfo.ASSUMED_CASH_RESERVES
    assert by_key["min_periods_for_forecast"] == predictive_forecaster.MIN_PERIODS_FOR_FORECAST


def test_known_gaps_flags_no_data_for_fresh_tenant(client, auth_headers):
    resp = client.post("/api/v1/insights/known-gaps", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert any(g["key"] == "no_data" for g in body["gaps"])


def test_known_gaps_flags_mrr_unavailable_after_upload_without_flag(client, auth_headers):
    csv_content = b"date,category,amount,description\n2026-01-05,Sales,1000,Row\n"
    client.post(
        "/api/finance/upload-ledger",
        files={"file": ("no_recurring_flag.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    resp = client.post("/api/v1/insights/known-gaps", headers=auth_headers)
    body = resp.json()
    assert any(g["key"] == "mrr_unavailable" for g in body["gaps"])
    assert not any(g["key"] == "no_data" for g in body["gaps"])


def test_ledger_rows_endpoint_after_upload(client, auth_headers):
    csv_content = b"date,category,amount,description\n2026-01-05,Sales,1000,Row\n"
    client.post(
        "/api/finance/upload-ledger",
        files={"file": ("ledger_rows_test.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    resp = client.post("/api/v1/finance/ledger-rows", json={}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["row_count"] == 1
    assert body["rows"][0]["row_id"] is not None


def test_category_suggestions_and_apply_round_trip(client, auth_headers):
    csv_content = (
        b"date,category,amount,description\n"
        b"2026-01-01,Software,50,Adobe Creative Cloud subscription\n"
        b"2026-01-02,Uncategorized,55,Adobe Illustrator renewal\n"
    )
    client.post(
        "/api/finance/upload-ledger",
        files={"file": ("categorize_test.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    resp = client.post("/api/v1/data/category-suggestions", headers=auth_headers)
    assert resp.status_code == 200
    suggestions = resp.json()["suggestions"]
    assert len(suggestions) == 1
    row_id = suggestions[0]["row_id"]
    assert suggestions[0]["suggested_category"] == "Software"

    apply_resp = client.post(
        "/api/v1/data/apply-category-suggestion",
        json={"row_id": row_id, "new_category": "Software"},
        headers=auth_headers,
    )
    assert apply_resp.status_code == 200
    assert apply_resp.json()["updated"] is True


def test_apply_category_suggestion_unknown_row_id_returns_404(client, auth_headers):
    resp = client.post(
        "/api/v1/data/apply-category-suggestion",
        json={"row_id": 999999999, "new_category": "Software"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_cross_tenant_data_isolation_via_api(client, auth_headers, make_auth_headers):
    headers_b = make_auth_headers("CLI-B-ISOLATED")
    csv_content = b"date,category,amount,description\n2026-01-05,Sales,12345,CLI-001 only\n"
    client.post(
        "/api/finance/upload-ledger",
        files={"file": ("isolation_test.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    resp_b = client.post("/api/v1/finance/ledger-rows", json={}, headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["row_count"] == 0


def test_security_headers_present(client):
    resp = client.get("/api/v1/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
