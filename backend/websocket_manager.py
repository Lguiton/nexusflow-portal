import json
import logging
from typing import Dict, Optional
 
from fastapi import WebSocket
 
logger = logging.getLogger("eivanta.websocket_manager")
 
 
class SwarmConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        # WS-01: a monotonic per-connection sequence counter, giving every
        # outbound message real "message identity" the client can check
        # ordering against. Reset to 0 on each fresh connect() below -- a
        # reconnect is a NEW connection, so its sequence starts over rather
        # than continuing the old connection's count (the client resets its
        # own expected-seq tracking the same way, keyed off the CONNECTED
        # message every fresh connection sends first -- see
        # SwarmLogStreamer.tsx).
        self.next_seq: Dict[str, int] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        existing = self.active_connections.get(session_id)
        if existing is not None and existing is not websocket:
            # A second connection arrived for a session_id that's already
            # tracked. Close the stale one explicitly rather than silently
            # overwriting it -- otherwise a later disconnect() call tied to
            # the OLD connection's lifecycle can delete the dict entry that
            # actually belongs to this NEW, still-open connection, orphaning
            # it from future broadcasts.
            logger.warning(f"Session '{session_id}' reconnected; closing previous connection.")
            try:
                await existing.close()
            except Exception:
                pass  # nosec B110 -- the stale connection may already be closed; nothing more to do either way
        self.active_connections[session_id] = websocket
        self.next_seq[session_id] = 0

    def disconnect(self, session_id: str, websocket: Optional[WebSocket] = None):
        # If the caller passes the specific websocket being torn down, only
        # remove the dict entry when it still points at THAT connection --
        # prevents a stale connection's disconnect from wiping out a newer,
        # still-live connection that reused the same session_id (see
        # connect() above). Callers that omit `websocket` keep the original
        # unconditional-delete behavior, for backward compatibility with
        # existing call sites until they're updated to pass it.
        current = self.active_connections.get(session_id)
        if current is None:
            return
        if websocket is None or current is websocket:
            del self.active_connections[session_id]
            # Only drop the sequence counter when the CURRENT connection is
            # the one being torn down -- a stale old connection's disconnect
            # (already a no-op above once `current is not websocket`) must
            # never reset the counter a newer, still-live connection is
            # actively using.
            self.next_seq.pop(session_id, None)

    async def _send(self, session_id: str, websocket: WebSocket, message: dict) -> None:
        """WS-01: stamps `seq` onto every outbound message before sending --
        the single choke point both broadcast_agent_step and send_to_session
        go through, so nothing leaves this manager without a sequence
        number."""
        message["seq"] = self.next_seq.get(session_id, 0)
        self.next_seq[session_id] = message["seq"] + 1
        await websocket.send_text(json.dumps(message))

    async def send_to_session(self, session_id: str, message: dict) -> None:
        """WS-01: for messages a route handler wants to send directly to its
        own connection (e.g. swarm.py's CONNECTED/HEARTBEAT messages), which
        previously called `websocket.send_text` straight from the route
        handler -- bypassing this manager entirely, and therefore never
        getting a seq stamp. No-op if the session isn't (or is no longer)
        connected."""
        websocket = self.active_connections.get(session_id)
        if websocket is None:
            return
        try:
            await self._send(session_id, websocket, message)
        except Exception as e:
            logger.warning(f"Send to session '{session_id}' failed, disconnecting: {e}")
            self.disconnect(session_id, websocket)

    async def broadcast_agent_step(self, session_id: str, agent: str, status: str, payload: dict):
        websocket = self.active_connections.get(session_id)
        if websocket is None:
            return
        message = {
            "agent": agent,
            "status": status,
            "payload": payload
        }
        try:
            await self._send(session_id, websocket, message)
        except Exception as e:
            logger.warning(f"Broadcast to session '{session_id}' failed, disconnecting: {e}")
            self.disconnect(session_id, websocket)
 
 
manager = SwarmConnectionManager()