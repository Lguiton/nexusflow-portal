import os
import re
import logging
from typing import Optional

import jwt
import bcrypt
from fastapi import Header, HTTPException

logger = logging.getLogger("eivanta.auth")

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


# RBAC-01: real password hashing. bcrypt has a hard 72-byte input limit
# (silently truncates beyond that in some bindings, raises in others,
# version-dependent) -- passwords are truncated to 72 bytes here
# explicitly before hashing, rather than trusting the library's own
# behavior, so hashing is deterministic regardless of which bcrypt
# version ends up installed. Written to bcrypt's documented API but not
# execution-verified -- PyPI is blocked in both of my sandboxes, so this
# is py_compile-clean and carefully reviewed, not run. See the delivery
# report for what to actually test once it's on a machine with real
# internet access.
def hash_password(plain_password: str) -> str:
    pw_bytes = plain_password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        pw_bytes = plain_password.encode("utf-8")[:72]
        return bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8"))
    except (ValueError, TypeError) as e:
        # A malformed/foreign-format hash should fail closed as "wrong
        # password", never raise past the login endpoint as a 500 that
        # might leak which emails have accounts vs. which have corrupt data.
        logger.warning(f"Password verification raised on a stored hash: {e}")
        return False


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


class AuthenticatedUser:
    """
    Real per-person identity, decoded from a real login-issued JWT (see
    backend/accounts.py). Deliberately a plain small class, not a
    pydantic model -- this never crosses a request/response boundary
    itself, it's only ever a FastAPI dependency's return value consumed
    by other Python code.
    """
    __slots__ = ("user_id", "client_id", "email", "role")

    def __init__(self, user_id: int, client_id: str, email: str, role: str):
        self.user_id = user_id
        self.client_id = client_id
        self.email = email
        self.role = role


async def verify_jwt_and_get_user(
    authorization: Optional[str] = Header(default=None),
) -> AuthenticatedUser:
    """
    Real per-person auth dependency -- use this (not
    verify_jwt_and_get_client_id) for any endpoint that needs to know WHO
    is asking, not just which tenant. Requires a token minted by the real
    /api/v1/auth/login endpoint; a token missing user_id/role claims
    (there shouldn't be any live ones once dev-login is retired, but this
    guards against a stale cached token from before this change) is
    rejected rather than defaulting to some role.
    """
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server authentication is not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    payload = _decode(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token.")
    raw_client_id = payload.get("client_id")
    user_id = payload.get("user_id")
    role = payload.get("role")
    email = payload.get("email")
    if not raw_client_id or user_id is None or not role:
        raise HTTPException(
            status_code=401,
            detail="Token is missing real user identity claims -- please log in again.",
        )
    return AuthenticatedUser(
        user_id=int(user_id),
        client_id=sanitize_client_id(str(raw_client_id)),
        email=str(email or ""),
        role=str(role),
    )


def require_role(*allowed_roles: str):
    """
    Dependency FACTORY, not a dependency itself -- call it with the roles
    an endpoint should allow, e.g.:

        @router.delete(...)
        async def remove_teammate(user: AuthenticatedUser = Depends(require_role("owner"))):

    Composes on top of verify_jwt_and_get_user (still runs full real auth
    first), then additionally rejects with 403 if that user's role isn't
    in allowed_roles. 403, not 404 -- an authenticated-but-unauthorized
    request should be told exactly that, not misled into thinking the
    resource doesn't exist.
    """
    async def _dependency(
        authorization: Optional[str] = Header(default=None),
    ) -> AuthenticatedUser:
        user = await verify_jwt_and_get_user(authorization=authorization)
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires one of these roles: {', '.join(allowed_roles)}.",
            )
        return user
    return _dependency


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
