import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health_check():
    # Was asserting "SECURE_ONLINE" -- the real /api/v1/health in main.py
    # has always returned "ONLINE". This would have failed on the very
    # first assertion of the whole suite.
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ONLINE"


def test_lean_intent_routing():
    """
    NOTE: this calls the real route_query(), which executes whichever
    specialist agent the router selects (e.g. generate_cfo_briefing,
    generate_forecast) for real -- that means a configured OPENAI_API_KEY
    and a reachable backend/nexusflow.duckdb are required to run this test,
    same as the existing test_db_manager_live.py convention in this repo.
    I could not execute this myself: FastAPI/DuckDB/OpenAI aren't
    installable in my review sandbox (no network access to those
    registries). The fix below was verified by reading the real,
    current orchestrator.py directly (signature, return shape, and the
    router's actual keyword table) rather than assumed -- but the actual
    run needs to happen in your dev environment.
    """
    from backend.agents.orchestrator import route_query

    def routed_agent(result: dict) -> str:
        # Previously checked result.get("routed_to", "") -- that key does
        # not exist anywhere in the real return shape. The routed agent's
        # name is nested inside agent_breakdown[0]["agent_name"], and it's
        # always lowercase snake_case (e.g. "data_engineer"), never the
        # Title-Case strings ("Data", "CFO") the old assertions checked
        # for -- Python's `in` is case-sensitive, so even fixing only the
        # key name would still have failed the string match.
        breakdown = result.get("agent_breakdown") or []
        return breakdown[0]["agent_name"] if breakdown else ""

    # route_query(query, client_id, ...) -- client_id has no default and
    # was previously omitted entirely, which would raise TypeError before
    # any assertion ran.
    test_client_id = "test_client_swarm"

    res1 = route_query("Show me historical ledger data", test_client_id)
    assert routed_agent(res1) == "data_engineer"  # matches the "data" keyword

    res2 = route_query("Forecast ARR for Q3 with confidence intervals", test_client_id)
    assert routed_agent(res2) == "predictive_forecaster"  # matches "forecast"

    # No keyword bucket in orchestrator.py's router matches "CFO briefing"
    # specifically -- it falls through to the router's default
    # (virtual_cfo). That's correct, expected behavior given the real
    # keyword table, not a bug: virtual_cfo IS the intended default handler.
    res3 = route_query("Give me an executive CFO briefing", test_client_id)
    assert routed_agent(res3) == "virtual_cfo"

    res4 = route_query("Upload and ingest transaction CSV batch", test_client_id)
    assert routed_agent(res4) == "data_engineer"  # matches "ingest"

    # Same default-fallback case as res3. There is no dedicated
    # security/audit routing bucket in this router's keyword table --
    # Ops Shield's threat screening happens BEFORE route_query is ever
    # called at all (in main.py's /api/search, as a separate pre-flight
    # check), not as a routable node inside this graph.
    res5 = route_query("Run security audit and system health check", test_client_id)
    assert routed_agent(res5) == "virtual_cfo"


def test_websocket_session_hijacking_guard():
    """
    The ORIGINAL version of this test could never fail, regardless of
    whether the vulnerability it claimed to check for was real: its
    "assert False, 'Security vulnerability...'" line was itself wrapped in
    a `try/except Exception: assert True` -- the AssertionError from a
    genuinely detected vulnerability was silently caught and reported as a
    PASS. Proven directly in this audit via a standalone simulation before
    ever touching this file.

    It also tested the wrong thing: two WebSocket connections sharing one
    session_id is not itself a security bug -- websocket_manager.py
    deliberately closes the older connection and takes over the slot,
    which is reasonable reconnect behavior, not a hijack.

    The REAL guard in swarm.py is that the token's own verified tenant
    (decoded server-side, never trusted from the client) must match the
    tenant named in the URL path -- a request presenting a valid token for
    one tenant must be rejected if the path claims a different tenant.
    This rewrite tests exactly that, using the real /api/v1/auth/dev-login
    endpoint to mint a genuine, validly-signed token (no mocking of the
    verification logic itself), and it structures the vulnerability
    assertion OUTSIDE any try/except so it can never be silently swallowed
    the way the original was.

    Requires JWT_SECRET to be configured in this test environment (same
    requirement as any other endpoint behind verify_jwt_and_get_client_id).
    """
    login_response = client.post("/api/v1/auth/dev-login", json={"client_id": "client_alpha"})
    assert login_response.status_code == 200, (
        "dev-login failed -- JWT_SECRET may not be configured in this test environment."
    )
    token_for_alpha = login_response.json()["access_token"]
    session_id = "secure_test_session_01"

    # Legitimate case: the token's own tenant matches the path. Must succeed.
    with client.websocket_connect(f"/ws/swarm/client_alpha/{session_id}?token={token_for_alpha}") as ws:
        first_message = ws.receive_json()
        assert first_message["status"] == "CONNECTED"

    # Hijacking attempt: client_alpha's VALID token, but the path claims to
    # be a different tenant, client_beta. swarm.py's guard compares the
    # token's verified client_id against the path's client_id and must
    # reject this before ever accepting the connection.
    handshake_accepted = True
    try:
        with client.websocket_connect(f"/ws/swarm/client_beta/{session_id}?token={token_for_alpha}"):
            handshake_accepted = True
    except Exception:
        # The server closing the handshake before accept() (WS_4008) is
        # the expected, correct outcome here -- this is what a properly
        # enforced guard looks like from the test client's side.
        handshake_accepted = False

    # This assertion is deliberately NOT inside the try/except above --
    # that separation is exactly what the original version got wrong.
    assert not handshake_accepted, (
        "Security vulnerability: a token issued for one tenant was accepted "
        "to open a WebSocket session under a different tenant's path."
    )
