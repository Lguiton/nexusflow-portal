"""
Real verification for POST /api/v1/predictive/scenario (COMP-03), added
26 Aug 2026. scenario_modeler.run_scenario is pure arithmetic on real
ledger data (via db_manager.get_ledger_chart_context) -- no mocking, no
LLM call, so these tests exercise the real code path end to end.
"""
import io

import pytest


def _upload_two_months(client, auth_headers):
    csv_content = (
        b"date,category,amount,description\n"
        b"2026-06-01,Sales,10000,June revenue\n"
        b"2026-06-05,Hosting,-2000,June infra\n"
        b"2026-07-01,Sales,12000,July revenue\n"
        b"2026-07-05,Hosting,-2000,July infra\n"
        b"2026-07-10,Payroll,-15000,July payroll\n"
    )
    resp = client.post(
        "/api/finance/upload-ledger",
        files={"file": ("ledger.csv", io.BytesIO(csv_content), "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


def test_scenario_requires_auth(client):
    resp = client.post("/api/v1/predictive/scenario", json={"scenario_type": "price_change_pct", "amount": 10})
    assert resp.status_code == 401


def test_scenario_no_data_state(client, auth_headers):
    resp = client.post(
        "/api/v1/predictive/scenario",
        json={"scenario_type": "price_change_pct", "amount": 10},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "NO_DATA"


def test_scenario_invalid_type_is_400_not_500(client, auth_headers):
    _upload_two_months(client, auth_headers)
    resp = client.post(
        "/api/v1/predictive/scenario",
        json={"scenario_type": "not_a_real_type", "amount": 10},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text


def test_scenario_price_change_pct(client, auth_headers):
    _upload_two_months(client, auth_headers)
    # Real baseline for July: revenue 12000, expense 2000+15000=17000, net -5000.
    resp = client.post(
        "/api/v1/predictive/scenario",
        json={"scenario_type": "price_change_pct", "amount": 10, "cash_reserves": 50000},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["baseline"]["monthly_revenue"] == 12000.0
    assert body["baseline"]["monthly_expense"] == 17000.0
    assert body["baseline"]["monthly_net"] == -5000.0
    assert body["projected"]["monthly_revenue"] == 13200.0  # 12000 * 1.10
    assert body["projected"]["monthly_expense"] == 17000.0
    assert body["projected"]["monthly_net"] == -3800.0
    assert body["assumed_cash_reserves"] == 50000
    assert body["baseline"]["cash_runway_months"] == 10.0  # 50000/5000
    assert body["projected"]["cash_runway_months"] == round(50000 / 3800, 1)
    assert body["runway_delta_months"] is not None and body["runway_delta_months"] > 0
    assert len(body["insights"]) == 2


def test_scenario_new_hire_monthly_cost(client, auth_headers):
    _upload_two_months(client, auth_headers)
    resp = client.post(
        "/api/v1/predictive/scenario",
        json={"scenario_type": "new_hire_monthly_cost", "amount": 6000, "cash_reserves": 50000},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["projected"]["monthly_expense"] == 23000.0  # 17000 + 6000
    assert body["projected"]["monthly_net"] == -11000.0
    assert body["projected"]["cash_runway_months"] == round(50000 / 11000, 1)
    # More burn -> shorter or equal runway than baseline
    assert body["projected"]["cash_runway_months"] <= body["baseline"]["cash_runway_months"]


def test_scenario_churned_account_monthly_revenue(client, auth_headers):
    _upload_two_months(client, auth_headers)
    resp = client.post(
        "/api/v1/predictive/scenario",
        json={"scenario_type": "churned_account_monthly_revenue", "amount": 4000, "cash_reserves": 50000},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["projected"]["monthly_revenue"] == 8000.0  # 12000 - 4000
    assert body["projected"]["monthly_net"] == -9000.0


def test_scenario_defaults_cash_reserves_when_omitted(client, auth_headers):
    _upload_two_months(client, auth_headers)
    resp = client.post(
        "/api/v1/predictive/scenario",
        json={"scenario_type": "price_change_pct", "amount": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Should fall back to the same constant Virtual CFO uses.
    from backend.agents.virtual_cfo import ASSUMED_CASH_RESERVES
    assert body["assumed_cash_reserves"] == ASSUMED_CASH_RESERVES


def test_scenario_rejects_missing_fields(client, auth_headers):
    resp = client.post("/api/v1/predictive/scenario", json={}, headers=auth_headers)
    assert resp.status_code == 422
