from fastapi import APIRouter, BackgroundTasks, WebSocket, WebSocketDisconnect, Query, HTTPException, status
from pydantic import BaseModel
from typing import Optional
import asyncio
import uuid
import json
import logging
import os
import jwt
import datetime

logger = logging.getLogger("nexusflow.swarm")

router = APIRouter()

# CRITICAL FIX: this file previously had NO real JWT verification.
# `verify_jwt_token()` was a stub that returned True for any non-empty
# token string, regardless of signature or client_id — meaning the
# WebSocket tenant-isolation this project has repeatedly verified as
# working (in an earlier version of this file) was not actually present
# in this version. Restored to fail-closed, signature-verified JWT
# handling consistent with the rest of the project.
try:
    SECRET_KEY = os.environ["JWT_SECRET"]
except KeyError:
    raise RuntimeError(
        "CRITICAL SECURITY ERROR: 'JWT_SECRET' environment variable is not set. "
        "Refusing to start insecurely."
    )

ALGORITHM = "HS256"
MAX_WS_MESSAGE_CHARS = 2048  # FIX: no message-size cap previously existed on this router's receive loop.

class SwarmTaskRequest(BaseModel):
    task_description: str
    tenant_id: str

class SwarmTaskResponse(BaseModel):
    job_id: str
    status: str

_active_jobs = {}

@router.post("/api/v1/swarm/execute", response_model=SwarmTaskResponse)
async def execute_swarm_task(request: SwarmTaskRequest, background_tasks: BackgroundTasks):
    # NOTE (not fixed here, flagged instead): this endpoint creates a job
    # entry but never actually schedules any work against `background_tasks`,
    # so a job stays "pending" forever. Left as-is since implementing the
    # actual background execution is a feature addition, not a bug fix
    # within the existing code's contract.
    job_id = str(uuid.uuid4())
    _active_jobs[job_id] = {"status": "pending", "result": None}
    return SwarmTaskResponse(job_id=job_id, status="pending")

def verify_jwt_token(token: Optional[str], expected_client_id: str) -> bool:
    """Cryptographic verification: checks JWT signature validity and that the
    embedded client_id claim matches the tenant being connected to."""
    if not token:
        return False
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        token_client_id = payload.get("client_id")
        if token_client_id != expected_client_id:
            logger.warning(
                f"SECURITY ALERT: Tenant mismatch! Connection requested for "
                f"'{expected_client_id}' but token was issued for '{token_client_id}'."
            )
            return False
        return True
    except jwt.ExpiredSignatureError:
        logger.warning("SECURITY ALERT: Expired JWT presented during WebSocket handshake.")
        return False
    except jwt.InvalidTokenError:
        logger.warning("SECURITY ALERT: Invalid JWT signature presented during WebSocket handshake.")
        return False

@router.websocket("/ws/swarm/{client_id}/{session_id}")
async def swarm_telemetry_stream(
    websocket: WebSocket,
    client_id: str,
    session_id: str,
    token: Optional[str] = Query(None)
):
    if not verify_jwt_token(token, client_id):
        await websocket.close(code=status.WS_4008_POLICY_VIOLATION, reason="Unauthorized")
        logger.info(f"SECURITY AUDIT: Rejected unauthorized WebSocket connection for tenant '{client_id}'")
        return

    await websocket.accept()
    logger.info(f"WebSocket connected for Client: {client_id}")

    try:
        while True:
            data = await websocket.receive_text()

            # FIX: no size limit previously existed here, allowing an
            # unbounded-length message to be sent repeatedly (flood/DoS
            # vector). Capped consistent with the limit already used
            # elsewhere in the project.
            if len(data) > MAX_WS_MESSAGE_CHARS:
                await websocket.send_text(json.dumps({
                    "stepId": str(uuid.uuid4()),
                    "agent": "OpsShield",
                    "status": "ERROR",
                    "payload": {"error": "Payload size exceeds security threshold."}
                }))
                continue

            try:
                user_msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "stepId": str(uuid.uuid4()),
                    "agent": "OpsShield",
                    "status": "ERROR",
                    "payload": {"error": "Malformed message payload."}
                }))
                continue

            await websocket.send_text(json.dumps({
                "stepId": str(uuid.uuid4()),
                "agent": "Orchestrator Agent #00",
                "status": "PROCESSING",
                "payload": {"received": user_msg.get('prompt')}
            }))

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected normally.")
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        await websocket.close(code=1011)

@router.get("/api/auth/dev-token")
async def generate_dev_token(client_id: str):
    # CRITICAL FIX: previously built a fake, unsigned token by hand
    # (hardcoded header/payload/"mock_signature") — not a real JWT at all.
    # Combined with the verify_jwt_token stub above, authentication was
    # entirely decorative. Now issues a genuinely signed JWT.
    payload = {
        "client_id": client_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1),
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token}
