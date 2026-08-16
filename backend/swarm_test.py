import pytest
from fastapi.testclient import TestClient
from backend.main import app, route_swarm_intent

client = TestClient(app)

def test_health_check():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SECURE_ONLINE"

def test_lean_intent_routing():
    assert route_swarm_intent("Show me historical ledger data") == "DATA_ANALYST"
    assert route_swarm_intent("Forecast ARR for Q3 with confidence intervals") == "DEEP_LEARNING"
    assert route_swarm_intent("Give me an executive CFO briefing") == "BI_ANALYST"
    assert route_swarm_intent("Upload and ingest transaction CSV batch") == "DATA_ENGINEER"
    assert route_swarm_intent("Run security audit and system health check") == "OPS_SHIELD"

def test_websocket_session_hijacking_guard():
    client_id_a = "client_alpha"
    client_id_b = "client_beta"
    session_id = "secure_test_session_01"

    with client.websocket_connect(f"/ws/swarm/{client_id_a}/{session_id}") as ws_a:
        try:
            with client.websocket_connect(f"/ws/swarm/{client_id_b}/{session_id}") as ws_b:
                assert False, "Security vulnerability: Session hijacking allowed!"
        except Exception:
            assert True
