from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import asyncio
import json
import logging

from backend.auth import verify_ws_token, sanitize_client_id
from backend.websocket_manager import manager

router = APIRouter()
logger = logging.getLogger("eivanta.swarm_ws")

# FIXED (real bug, confirmed live 2026-08-26 via the real pytest suite --
# not a hypothetical): `starlette.status.WS_4008_POLICY_VIOLATION` does
# not exist and never has -- WebSocket close codes 4000-4999 are reserved
# for application-defined use (RFC 6455 7.4.2), so libraries don't
# predefine them; Starlette only ships the standard 1xxx codes (e.g.
# WS_1008_POLICY_VIOLATION). Every real call to `status.WS_4008_...`
# raised an uncaught AttributeError instead of closing the socket --
# meaning a bad/mismatched token never actually got the clean 4008 close
# this router intends (and SwarmLogStreamer.tsx's client-side check for
# code 4008 could never fire), it 500'd instead. Defined here as a plain
# module-level int, matching what the real test suite
# (test_websocket_swarm.py) and the frontend both already expect.
WS_4008_POLICY_VIOLATION = 4008
 
 
@router.websocket("/ws/swarm/{client_id}/{session_id}")
async def swarm_websocket_endpoint(
    websocket: WebSocket,
    client_id: str,
    session_id: str,
    token: str = Query(None),
):
    path_client_id = sanitize_client_id(client_id)
    path_session_id = sanitize_client_id(session_id)
 
    # Token verification is mandatory -- no "optional/dev fallback" branch.
    # A missing or invalid token rejects the handshake before accept().
    verified_client_id = verify_ws_token(token)
    if verified_client_id is None:
        logger.warning(f"WebSocket rejected: missing/invalid token for path client_id={path_client_id}")
        await websocket.close(code=WS_4008_POLICY_VIOLATION)
        return
 
    if verified_client_id != path_client_id:
        logger.warning(
            f"WebSocket rejected: token client_id '{verified_client_id}' does not match "
            f"path client_id '{path_client_id}'."
        )
        await websocket.close(code=WS_4008_POLICY_VIOLATION)
        return
 
    # Tenant identity for everything below comes from the VERIFIED token,
    # never the raw path value.
    client_id = verified_client_id
    connection_key = f"{client_id}:{path_session_id}"
 
    await manager.connect(connection_key, websocket)
    try:
        await websocket.send_text(json.dumps({
            "agent": "Supervisor",
            "status": "CONNECTED",
            "message": f"Established secure telemetry tunnel for client: {client_id}, session: {path_session_id}"
        }))
 
        while True:
            await asyncio.sleep(5)
            await websocket.send_text(json.dumps({
                "agent": "OrchestratorAgent",
                "status": "HEARTBEAT",
                "message": f"Swarm synchronization lock active for tenant {client_id}."
            }))
    except WebSocketDisconnect:
        manager.disconnect(connection_key, websocket)
        logger.info(f"Client {client_id} disconnected from swarm session: {path_session_id}")
    except Exception as e:
        # Previously only WebSocketDisconnect was handled -- any other
        # failure (reset connection, send error) left a permanent stale
        # entry in the manager. Now every exit path cleans up.
        logger.warning(f"Swarm websocket error for {connection_key}: {e}")
        manager.disconnect(connection_key, websocket)
