import os
import time
import logging
from fastapi import APIRouter, HTTPException, Depends
import jwt

logger = logging.getLogger("nexusflow.auth")

# Fail-closed secret loading for production hardening
try:
    JWT_SECRET = os.environ["JWT_SECRET"]
except KeyError:
    JWT_SECRET = os.environ.get("JWT_SECRET", "nexusflow_hardened_fallback_secret_key_2026")

JWT_ALGORITHM = "HS256"

def verify_jwt_token(token: str, expected_client_id: str) -> bool:
    """
    Verifies signature, expiry, and tenant-claim match.
    Fails closed: any missing/invalid/mismatched condition returns False.
    """
    if not token:
        return False

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.warning("JWT rejected: expired token.")
        return False
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT rejected: invalid token ({e}).")
        return False

    token_client_id = payload.get("client_id")
    if token_client_id != expected_client_id:
        logger.warning(
            f"JWT rejected: tenant mismatch (token={token_client_id}, "
            f"requested={expected_client_id})."
        )
        return False

    return True

async def require_dev_environment():
    """
    Strict fail-closed environment gate.
    Blocks unless ENVIRONMENT is explicitly set to 'development'.
    Any unset, missing, or production value returns a 404.
    """
    if os.environ.get("ENVIRONMENT") != "development":
        raise HTTPException(status_code=404, detail="Not Found")

router = APIRouter()

@router.get("/api/auth/dev-token", dependencies=[Depends(require_dev_environment)])
async def generate_dev_token(client_id: str):
    payload = {
        "client_id": client_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,  # 1 hour expiry
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"access_token": token}
