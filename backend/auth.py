import os
import re
import logging
from typing import Optional
 
import jwt
from fastapi import Header, HTTPException
 
logger = logging.getLogger("nexusflow.auth")
 
# Reconciled with swarm.py's existing convention: one JWT_SECRET env var,
# no hardcoded fallback. The previous fallback in swarm.py
# ("hardened_secret_key_change_in_production") was a real secret sitting in
# source control -- anyone with repo access could forge tokens with it.
JWT_SECRET = os.environ.get("JWT_SECRET")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
 
if not JWT_SECRET:
    logger.critical(
        "JWT_SECRET is not set. All REST and WebSocket endpoints that "
        "depend on verify_jwt_and_get_client_id / verify_ws_token will "
        "reject every request until this is configured."
    )
 
 
def sanitize_client_id(client_id: str) -> str:
    return re.sub(r'[^A-Za-z0-9_-]', '', client_id or "")[:128] or "default_client"
 
 
def _decode(token: str) -> Optional[dict]:
    if not JWT_SECRET or not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT verification failed: {e}")
        return None
 
 
async def verify_jwt_and_get_client_id(
    authorization: Optional[str] = Header(default=None),
) -> str:
    """FastAPI dependency for REST endpoints (Authorization: Bearer <token>)."""
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server authentication is not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    payload = _decode(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token.")
    raw_client_id = payload.get("client_id") or payload.get("tenant_id") or payload.get("sub")
    if not raw_client_id:
        raise HTTPException(status_code=401, detail="Token is missing tenant identity claim.")
    return sanitize_client_id(str(raw_client_id))
 
 
def verify_ws_token(token: Optional[str]) -> Optional[str]:
    """
    WebSocket routes receive the token as a query param, not a header.
    Returns the sanitized, VERIFIED client_id, or None if missing/invalid --
    the caller is responsible for closing the socket on None.
    """
    if not token:
        return None
    payload = _decode(token)
    if payload is None:
        return None
    raw_client_id = payload.get("client_id") or payload.get("tenant_id") or payload.get("sub")
    if not raw_client_id:
        return None
    return sanitize_client_id(str(raw_client_id))
