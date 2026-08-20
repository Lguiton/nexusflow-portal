import json
import logging
from fastapi import WebSocket

logger = logging.getLogger("nexusflow.websocket_manager")

class SwarmConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]

    async def broadcast_agent_step(self, session_id: str, agent: str, status: str, payload: dict):
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            message = {
                "agent": agent,
                "status": status,
                "payload": payload
            }
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                # FIX: silent `except Exception: pass`-style failures make
                # dropped connections invisible in logs. Now logged before
                # cleanup, so a broken broadcast is visible in server logs
                # rather than disappearing silently.
                logger.warning(f"Broadcast to session '{session_id}' failed, disconnecting: {e}")
                self.disconnect(session_id)

# The () here is critical! It creates the instance so `self` is handled correctly.
manager = SwarmConnectionManager()
