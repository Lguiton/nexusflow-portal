"""
Real WebSocket auth tests for /ws/swarm/{client_id}/{session_id}
(backend/routers/swarm.py). Exercises the exact server-side behavior
frontend/components/SwarmLogStreamer.tsx depends on: a missing or invalid
token, and a token/path client_id mismatch, both close with code 4008
(WS_4008_POLICY_VIOLATION) -- and a valid, matching token connects and
receives a real CONNECTED message before falling into the heartbeat loop.

WS-01 (27 Aug 2026): also covers message identity/ordering -- every
outbound message on a connection carries a real, monotonic `seq` (see
websocket_manager.py's SwarmConnectionManager), starting at 0 for the
CONNECTED message every fresh connection sends first, and resetting back
to 0 for a brand-new connection rather than continuing a prior one's count.

TEN-02 (27 Aug 2026): also covers the suspension gate this route was
disclosed as missing -- a real, live-suspended tenant's otherwise-valid,
matching token must still be rejected with 4008, the same as a bad token,
and reactivating must restore the connection. Suspension is performed
through the real /api/v1/tenant/suspend REST endpoint (never by poking
the DB directly), so these tests exercise the exact same code path a real
suspended tenant would hit.
"""
import asyncio

import pytest
from starlette.websockets import WebSocketDisconnect

from backend.websocket_manager import SwarmConnectionManager


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


def test_connected_message_carries_seq_zero(client, auth_headers):
    # WS-01: the CONNECTED message is always the first thing a fresh
    # connection sends -- SwarmLogStreamer.tsx anchors its own expected-seq
    # tracking against exactly this being seq=0.
    token = auth_headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect(f"/ws/swarm/CLI-001/test-session?token={token}") as websocket:
        data = websocket.receive_json()
        assert data["seq"] == 0


# ---------------------------------------------------------------------------
# WS-01: SwarmConnectionManager's sequencing directly (no real socket
# needed) -- broadcast_agent_step/send_to_session both stamp seq through
# the same _send() choke point, and a fresh connect() resets the counter.
# ---------------------------------------------------------------------------

class _RecordingWebSocket:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(text)

    async def close(self):
        pass


def test_broadcast_agent_step_seq_increments_monotonically():
    import json

    manager = SwarmConnectionManager()
    ws = _RecordingWebSocket()

    async def _run():
        await manager.connect("sess-1", ws)
        await manager.broadcast_agent_step("sess-1", "bi_engineer", "RUNNING", {"a": 1})
        await manager.broadcast_agent_step("sess-1", "bi_engineer", "COMPLETE", {"a": 2})

    asyncio.run(_run())

    seqs = [json.loads(m)["seq"] for m in ws.sent]
    assert seqs == [0, 1]


def test_send_to_session_and_broadcast_agent_step_share_one_sequence():
    # WS-01: send_to_session (used for CONNECTED/HEARTBEAT) and
    # broadcast_agent_step (used for real agent-step telemetry) must never
    # each keep their own counter -- a client relying on seq for ordering
    # needs ONE sequence across every message type on the connection.
    import json

    manager = SwarmConnectionManager()
    ws = _RecordingWebSocket()

    async def _run():
        await manager.connect("sess-1", ws)
        await manager.send_to_session("sess-1", {"agent": "Supervisor", "status": "CONNECTED", "message": "hi"})
        await manager.broadcast_agent_step("sess-1", "bi_engineer", "RUNNING", {})
        await manager.send_to_session("sess-1", {"agent": "OrchestratorAgent", "status": "HEARTBEAT", "message": "hb"})

    asyncio.run(_run())

    seqs = [json.loads(m)["seq"] for m in ws.sent]
    assert seqs == [0, 1, 2]


def test_reconnect_resets_sequence_to_zero():
    # A fresh connect() for the same session_id (a real reconnect) must
    # start the sequence over, not continue the previous connection's
    # count -- SwarmLogStreamer.tsx resets its own expected-seq the same
    # way, keyed off this.
    import json

    manager = SwarmConnectionManager()
    ws1 = _RecordingWebSocket()
    ws2 = _RecordingWebSocket()

    async def _run():
        await manager.connect("sess-1", ws1)
        await manager.broadcast_agent_step("sess-1", "bi_engineer", "RUNNING", {})
        await manager.broadcast_agent_step("sess-1", "bi_engineer", "COMPLETE", {})
        # A new connection for the SAME session_id -- connect() itself
        # closes the stale one and resets next_seq (see websocket_manager.py).
        await manager.connect("sess-1", ws2)
        await manager.broadcast_agent_step("sess-1", "bi_engineer", "RUNNING", {})

    asyncio.run(_run())

    assert [json.loads(m)["seq"] for m in ws1.sent] == [0, 1]
    assert [json.loads(m)["seq"] for m in ws2.sent] == [0]


# ---------------------------------------------------------------------------
# TEN-02: WebSocket route wired to the tenant-suspension gate.
# ---------------------------------------------------------------------------

def test_suspended_tenant_ws_connection_rejected_with_4008(client, make_auth_headers):
    owner_headers = make_auth_headers("WSTEN-01", role="owner")
    suspend_resp = client.post("/api/v1/tenant/suspend", headers=owner_headers)
    assert suspend_resp.status_code == 200, suspend_resp.text

    token = owner_headers["Authorization"].split(" ", 1)[1]
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/swarm/WSTEN-01/test-session?token={token}"):
            pass
    assert exc_info.value.code == 4008


def test_active_tenant_ws_connection_still_works_alongside_suspension_gate(client, auth_headers):
    # Regression guard: adding the suspension check must not break the
    # ordinary, never-suspended case this whole test file otherwise covers.
    token = auth_headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect(f"/ws/swarm/CLI-001/test-session?token={token}") as websocket:
        data = websocket.receive_json()
        assert data["status"] == "CONNECTED"


def test_reactivated_tenant_ws_connection_works_again(client, make_auth_headers):
    owner_headers = make_auth_headers("WSTEN-02", role="owner")
    token = owner_headers["Authorization"].split(" ", 1)[1]

    suspend_resp = client.post("/api/v1/tenant/suspend", headers=owner_headers)
    assert suspend_resp.status_code == 200, suspend_resp.text

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/swarm/WSTEN-02/test-session?token={token}"):
            pass
    assert exc_info.value.code == 4008

    reactivate_resp = client.post("/api/v1/tenant/reactivate", headers=owner_headers)
    assert reactivate_resp.status_code == 200, reactivate_resp.text

    with client.websocket_connect(f"/ws/swarm/WSTEN-02/test-session?token={token}") as websocket:
        data = websocket.receive_json()
        assert data["status"] == "CONNECTED"


def test_suspending_one_tenant_does_not_affect_another_tenants_ws_connection(client, make_auth_headers):
    owner_a = make_auth_headers("WSTEN-03-A", role="owner")
    owner_b = make_auth_headers("WSTEN-03-B", role="owner")
    token_b = owner_b["Authorization"].split(" ", 1)[1]

    suspend_resp = client.post("/api/v1/tenant/suspend", headers=owner_a)
    assert suspend_resp.status_code == 200, suspend_resp.text

    # Tenant B was never touched -- its WS connection must be completely
    # unaffected by tenant A's suspension.
    with client.websocket_connect(f"/ws/swarm/WSTEN-03-B/test-session?token={token_b}") as websocket:
        data = websocket.receive_json()
        assert data["status"] == "CONNECTED"


def test_is_tenant_suspended_helper_matches_lifecycle_status(isolated_db):
    # Direct unit coverage of the new backend.auth.is_tenant_suspended
    # helper itself, independent of the WebSocket route -- proves it
    # tracks real lifecycle_status transitions (active -> suspended ->
    # active), and fails OPEN (not suspended) for a client_id with no
    # tenant row at all, matching _raise_if_suspended's own documented
    # trade-off for that same data-anomaly case.
    from backend.auth import is_tenant_suspended

    async def _run():
        await isolated_db.create_tenant_and_owner(
            "WSTEN-04", "Test Tenant WSTEN-04", "wsten-04-owner@test.example", "irrelevant-hash",
        )
        assert await is_tenant_suspended("WSTEN-04") is False

        await isolated_db.suspend_tenant("WSTEN-04", suspended_by_user_id=1)
        assert await is_tenant_suspended("WSTEN-04") is True

        await isolated_db.reactivate_tenant("WSTEN-04")
        assert await is_tenant_suspended("WSTEN-04") is False

        assert await is_tenant_suspended("NO-SUCH-TENANT-AT-ALL") is False

    asyncio.run(_run())
