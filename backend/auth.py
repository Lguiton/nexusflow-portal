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


def _decode_and_build_user(authorization: Optional[str]) -> AuthenticatedUser:
    """
    Core JWT-decode-to-identity logic, shared by verify_jwt_and_get_user and
    verify_jwt_and_get_user_allow_suspended below. Deliberately has NO
    opinion on tenant lifecycle state (see TEN-01/TEN-02) -- that's layered
    on top by the two public wrappers, not duplicated in each.
    """
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server authentication is not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    payload = _decode(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token.")
    if payload.get("mfa_challenge"):
        # AUTH-04: a challenge token is minted by login() ONLY to let its
        # holder complete /api/v1/auth/mfa/verify -- it must never work as
        # a real access token anywhere else, or MFA would be pure theater
        # (a stolen challenge token could just skip the second factor
        # entirely by hitting any other protected endpoint directly).
        raise HTTPException(
            status_code=401,
            detail="This token can only be used to complete MFA verification.",
        )
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


async def _tenant_lifecycle_status(client_id: str) -> Optional[str]:
    try:
        from backend import db_manager
    except ImportError:
        import db_manager  # type: ignore
    return await db_manager.get_tenant_lifecycle_status(client_id)


async def _raise_if_suspended(client_id: str) -> None:
    """
    TEN-01/TEN-02: shared suspension gate. A missing tenant ROW (get_tenant_
    lifecycle_status returns None) is treated as "not suspended" rather than
    rejected -- a real, already-issued JWT should always have a matching
    tenant row (they're created together in create_tenant_and_owner), so
    this branch is a defensive fallback for a data anomaly, not an expected
    path; failing OPEN here means a data-integrity bug degrades to "acts as
    if active" rather than locking every tenant out of the whole app.
    Suspension itself (a real, deliberately-set value) still fails CLOSED --
    that's the actual security property TEN-01/TEN-02 exists to provide.
    """
    status = await _tenant_lifecycle_status(client_id)
    if status == "suspended":
        raise HTTPException(
            status_code=423,
            detail=(
                "This tenant account is suspended. An owner can reactivate it "
                "from Trust & Gaps, or export/delete the tenant's data."
            ),
        )


async def is_tenant_suspended(client_id: str) -> bool:
    """
    TEN-02 (27 Aug 2026): the WebSocket equivalent of _raise_if_suspended.
    A WebSocket route can't return an HTTP response, so it can't raise
    HTTPException -- the caller (backend/routers/swarm.py) checks this bool
    itself and closes the socket. Shares the exact same underlying lookup
    and the same fail-OPEN-on-missing-row / fail-CLOSED-on-real-suspension
    trade-off as _raise_if_suspended above, so the two paths can never
    silently disagree about whether a given tenant is suspended.

    This was the one disclosed gap left open by TEN-02's original pass
    (see the v2.4->v2.5 Change Log): every REST endpoint got the
    suspension gate for free through verify_jwt_and_get_user, but the
    swarm WebSocket route authenticates through the separate
    verify_ws_token path and was never wired to it -- a suspended tenant
    could still open a live swarm-telemetry connection.
    """
    return await _tenant_lifecycle_status(client_id) == "suspended"


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

    TEN-01/TEN-02: also enforces the tenant-suspension gate (423 if
    suspended) -- since every existing protected endpoint in this codebase
    already depends on THIS function (directly, or via require_role below),
    that single check point covers the whole app for free, with zero
    per-endpoint changes needed elsewhere. The narrow exception is the
    handful of tenant-lifecycle-management endpoints themselves (status,
    reactivate, export, delete) -- those use
    verify_jwt_and_get_user_allow_suspended instead, specifically so a
    suspended tenant's owner is never locked out of the one action
    (reactivate) that gets them unstuck.
    """
    user = _decode_and_build_user(authorization)
    await _raise_if_suspended(user.client_id)
    return user


async def verify_jwt_and_get_user_allow_suspended(
    authorization: Optional[str] = Header(default=None),
) -> AuthenticatedUser:
    """
    Identical to verify_jwt_and_get_user, MINUS the suspension gate. Use
    this ONLY for endpoints that must keep working while a tenant is
    suspended: GET /api/v1/auth/me (so the frontend can even learn it's
    suspended and show that state), GET /api/v1/tenant/status, POST
    /api/v1/tenant/{suspend,reactivate}, GET /api/v1/tenant/export, and
    DELETE /api/v1/tenant. Every other endpoint in the app should keep
    using verify_jwt_and_get_user (or require_role, which wraps it) so the
    suspension gate actually means something.
    """
    return _decode_and_build_user(authorization)


def require_role(*allowed_roles: str):
    """
    Dependency FACTORY, not a dependency itself -- call it with the roles
    an endpoint should allow, e.g.:

        @router.delete(...)
        async def remove_teammate(user: AuthenticatedUser = Depends(require_role("owner"))):

    Composes on top of verify_jwt_and_get_user (still runs full real auth
    AND the suspension gate first), then additionally rejects with 403 if
    that user's role isn't in allowed_roles. 403, not 404 -- an
    authenticated-but-unauthorized request should be told exactly that, not
    misled into thinking the resource doesn't exist.
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


def require_role_allow_suspended(*allowed_roles: str):
    """
    Same role-gating as require_role, but built on
    verify_jwt_and_get_user_allow_suspended -- for the tenant-lifecycle
    endpoints that must remain reachable by their allowed role(s) even
    while the tenant is suspended (see that function's own docstring for
    exactly which endpoints this is for, and why).
    """
    async def _dependency(
        authorization: Optional[str] = Header(default=None),
    ) -> AuthenticatedUser:
        user = await verify_jwt_and_get_user_allow_suspended(authorization=authorization)
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires one of these roles: {', '.join(allowed_roles)}.",
            )
        return user
    return _dependency


class MfaChallenge:
    """
    AUTH-04: identity carried by a short-lived MFA challenge token (minted
    by login() when the account has MFA enabled -- see backend/accounts.py's
    _mint_mfa_challenge_token). Deliberately a SEPARATE class from
    AuthenticatedUser, not a reused/relaxed version of it -- code that
    receives an MfaChallenge cannot accidentally be handed a real
    AuthenticatedUser's worth of trust by a type-checker or a careless
    isinstance check, since the two types are unrelated.
    """
    __slots__ = ("user_id", "client_id", "email", "role")

    def __init__(self, user_id: int, client_id: str, email: str, role: str):
        self.user_id = user_id
        self.client_id = client_id
        self.email = email
        self.role = role


async def verify_mfa_challenge_token(
    authorization: Optional[str] = Header(default=None),
) -> MfaChallenge:
    """
    AUTH-04: the ONLY dependency that accepts an MFA challenge token --
    every other dependency in this file explicitly REJECTS one (see
    _decode_and_build_user's own check above). Used solely by
    POST /api/v1/auth/mfa/verify, the second step of a login for an
    account with MFA enabled.
    """
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server authentication is not configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    payload = _decode(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired MFA challenge -- please log in again.")
    if not payload.get("mfa_challenge"):
        raise HTTPException(status_code=401, detail="This token is not a valid MFA challenge token.")
    raw_client_id = payload.get("client_id")
    user_id = payload.get("user_id")
    role = payload.get("role")
    email = payload.get("email")
    if not raw_client_id or user_id is None or not role:
        raise HTTPException(status_code=401, detail="MFA challenge token is missing identity claims.")
    return MfaChallenge(
        user_id=int(user_id),
        client_id=sanitize_client_id(str(raw_client_id)),
        email=str(email or ""),
        role=str(role),
    )


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


def best_effort_tenant_id_from_authorization_header(
    authorization: Optional[str],
) -> Optional[str]:
    """
    API-03: lightweight, side-effect-free JWT decode used ONLY to pick a
    rate-limiting bucket key in main.py's enforce_api_rate_limits
    middleware -- this is NOT a real auth check and must never be used to
    authorize anything. Deliberately more lenient than every real auth
    dependency above: it does not raise on failure (returns None
    instead), does not enforce tenant suspension, and does not reject an
    MFA challenge token's client_id the way _decode_and_build_user does --
    any request carrying ANY validly-signed token, even one a real
    endpoint would go on to reject for a different reason, still
    identifies a real tenant worth rate-limiting BY that tenant rather
    than falling back to the tighter, shared-across-everyone-unauthenticated
    IP bucket. Returning None here only ever makes the CALLER's behavior
    MORE restrictive (IP-based instead of tenant-based), never less -- so
    the leniency here is not a security bypass.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    payload = _decode(token)
    if not payload:
        return None
    raw_client_id = payload.get("client_id") or payload.get("tenant_id") or payload.get("sub")
    if not raw_client_id:
        return None
    return sanitize_client_id(str(raw_client_id))
