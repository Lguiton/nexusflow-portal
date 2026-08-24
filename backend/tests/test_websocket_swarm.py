"""
Real WebSocket auth tests for /ws/swarm/{client_id}/{session_id}
(backend/routers/swarm.py). Exercises the exact server-side behavior
frontend/components/SwarmLogStreamer.tsx depends on: a missing or invalid
token, and a token/path client_id mismatch, both close with code 4008
(WS_4008_POLICY_VIOLATION) -- and a valid, matching token connects and
receives a real CONNECTED message before falling into the heartbeat loop.
"""
import pytest
from starlette.websockets import WebSocketDisconnect


def test_missing_token_rejected_with_4008(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/swarm/CLI-001/test-session"):
            pass
    assert exc_info.value.code == 4008


def test_invalid_token_rejected_with_4008(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/swarm/CLI-001/test-session?token=not.a.real.jwt"):
            pass
    assert exc_info.value.code == 4008


def test_token_client_id_mismatch_rejected_with_4008(client, auth_headers):
    # auth_headers is minted for CLI-001 (see conftest.py); connecting on a
    # DIFFERENT path client_id must be rejected even though the token
    # itself is genuinely valid -- this is the server-side guarantee
    # SwarmLogStreamer.tsx's restored comment relies on instead of a
    # redundant client-side JWT decode.
    token = auth_headers["Authorization"].split(" ", 1)[1]
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/swarm/CLI-999-DIFFERENT/test-session?token={token}"):
            pass
    assert exc_info.value.code == 4008


def test_valid_matching_token_connects_and_sends_connected_message(client, auth_headers):
    token = auth_headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect(f"/ws/swarm/CLI-001/test-session?token={token}") as websocket:
        data = websocket.receive_json()
        assert data["status"] == "CONNECTED"
        assert "CLI-001" in data["message"]
