from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
import json
import asyncio
import os
import jwt
from typing import Optional

router = APIRouter()

# CRITICAL FIX: Fail loudly at startup if JWT_SECRET is missing (Fail-Closed principle)
try:
    SECRET_KEY = os.environ["JWT_SECRET"]
except KeyError:
    raise RuntimeError("CRITICAL SECURITY ERROR: 'JWT_SECRET' environment variable is not set. Refusing to start insecurely.")

ALGORITHM = "HS256"

def verify_tenant_authorization(client_id: str, token: Optional[str]) -> bool:
    """
    Cryptographic Enterprise Security Check:
    Verifies JWT signature and ensures the embedded client_id claim matches the URL route.
    """
    if not token:
        return False
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        token_client_id = payload.get("client_id")
        
        # Strict tenant boundary verification
        if token_client_id != client_id:
            print(f"SECURITY ALERT: Tenant mismatch! URL client '{client_id}' does not match token client '{token_client_id}'")
            return False
            
        return True
    except jwt.ExpiredSignatureError:
        print("SECURITY ALERT: Expired JWT token presented during WebSocket handshake.")
        return False
    except jwt.InvalidTokenError:
        print("SECURITY ALERT: Invalid JWT signature presented during WebSocket handshake.")
        return False

@router.websocket("/ws/swarm/{client_id}/{session_id}")
async def swarm_websocket(
    websocket: WebSocket, 
    client_id: str, 
    session_id: str,
    token: Optional[str] = Query(None)
):
    # 1. Enforce Cryptographic Server-Side Tenant Authentication
    if not verify_tenant_authorization(client_id, token):
        await websocket.close(code=status.WS_4008_POLICY_VIOLATION, reason="Unauthorized: Cryptographic token validation failed.")
        print(f"SECURITY AUDIT: Rejected unauthorized WebSocket connection for tenant '{client_id}'")
        return

    await websocket.accept()
    print(f"Cryptographically verified Swarm connected for tenant: {client_id}, session: {session_id}")
    
    try:
        await websocket.send_text(json.dumps({
            "agent": "Supervisor",
            "status": "COMPLETE",
            "payload": {"message": f"Cryptographically secured session active for tenant {client_id}"},
            "stepId": "init-0"
        }))

        while True:
            data = await websocket.receive_text()
            
            # Backend message size rate-limiting check
            if len(data) > 2048:
                await websocket.send_text(json.dumps({
                    "agent": "OpsShield",
                    "status": "ERROR",
                    "payload": {"error": "Payload size exceeds security threshold."},
                    "stepId": "err-limit"
                }))
                continue

            message_data = json.loads(data)
            prompt = message_data.get("prompt", "")
            
            agents = ["DataEngineer", "AISystemAgent", "BIAnalytics", "VirtualCFO"]
            
            for idx, agent in enumerate(agents):
                step_id = f"step-{idx}"
                await websocket.send_text(json.dumps({
                    "agent": agent,
                    "status": "PROCESSING",
                    "payload": {"query": prompt, "status": "Executing secure tenant-isolated pipeline..."},
                    "stepId": step_id
                }))
                await asyncio.sleep(0.6)
                
                await websocket.send_text(json.dumps({
                    "agent": agent,
                    "status": "COMPLETE",
                    "payload": {"result": f"Securely processed '{prompt}' for verified tenant {client_id}"},
                    "stepId": step_id
                }))
                await asyncio.sleep(0.3)

    except WebSocketDisconnect:
        print(f"Swarm disconnected for tenant: {client_id}")
    except Exception as e:
        print(f"Swarm error: {e}")