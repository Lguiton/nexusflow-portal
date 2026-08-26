import json
import logging
from typing import Dict, Optional
 
from fastapi import WebSocket
 
logger = logging.getLogger("eivanta.websocket_manager")
 
 
class SwarmConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
 
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
                pass
        self.active_connections[session_id] = websocket
 
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
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"Broadcast to session '{session_id}' failed, disconnecting: {e}")
            self.disconnect(session_id, websocket)
 
 
manager = SwarmConnectionManager()