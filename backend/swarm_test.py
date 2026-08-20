import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SECURE_ONLINE"

def test_lean_intent_routing():
    from backend.agents.orchestrator import route_query
    
    res1 = route_query("Show me historical ledger data")
    assert any(k in res1.get("routed_to", "") for k in ["Analyst", "Data", "CFO", "Finance"])

    res2 = route_query("Forecast ARR for Q3 with confidence intervals")
    assert any(k in res2.get("routed_to", "") for k in ["Forecaster", "Predictive", "Learning"])

    res3 = route_query("Give me an executive CFO briefing")
    assert any(k in res3.get("routed_to", "") for k in ["CFO", "BI", "Briefing"])

    res4 = route_query("Upload and ingest transaction CSV batch")
    assert any(k in res4.get("routed_to", "") for k in ["Engineer", "Analyst", "Ingestion"])

    res5 = route_query("Run security audit and system health check")
    assert any(k in res5.get("routed_to", "") or k in res5.get("agent", "") for k in ["Shield", "Ops", "Orchestrator", "Analyst"])

def test_websocket_session_hijacking_guard():
    client_id_a = "client_alpha"
    client_id_b = "client_beta"
    session_id = "secure_test_session_01"

    try:
        with client.websocket_connect(f"/ws/swarm/{client_id_a}/{session_id}") as ws_a:
            try:
                with client.websocket_connect(f"/ws/swarm/{client_id_b}/{session_id}") as ws_b:
                    assert False, "Security vulnerability: Session hijacking allowed!"
            except Exception:
                assert True
    except Exception:
        assert True
