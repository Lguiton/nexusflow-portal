"""
INT-01: scoped API key management for the MCP read-only tool server
(backend/mcp_server.py).

Owner/admin only, same posture as BYOK settings (backend/byok.py) --
these keys grant read access to a tenant's real financial/analytics data
to whatever external tool holds them, so creating or revoking one is a
sensitive action, not a routine member-level one.

The raw key is returned exactly once, in the create response below --
db_manager.py never persists anything but its SHA-256 hash. A caller that
loses the response has no way to recover the key; they generate a new one
and revoke the old one from this same router's DELETE endpoint.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field

try:
    from backend import db_manager
    from backend.auth import require_role, AuthenticatedUser
    from backend import idempotency
except ImportError:
    import db_manager
    from auth import require_role, AuthenticatedUser
    import idempotency

router = APIRouter()
logger = logging.getLogger("eivanta.api_keys")


class CreateApiKeyRequest(BaseModel):
    label: str = Field("", max_length=200)


@router.post("/api/v1/settings/api-keys", tags=["Settings"])
async def create_api_key(
    request: Request,
    req: CreateApiKeyRequest = CreateApiKeyRequest(),
    user: AuthenticatedUser = Depends(require_role("owner", "admin")),
):
    # API-02: opt-in idempotency. Unlike invite_teammate, this endpoint
    # has NO natural duplicate guard at all -- two labels can be
    # identical, so a network retry with no Idempotency-Key header would
    # silently mint a second real key today. A replayed request returns
    # the exact original response, including its one-time raw api_key --
    # correct: the client never actually received it the first time, so
    # handing it back again on a genuine replay is the whole point, not a
    # leak (the request is authenticated as the same tenant either way).
    idempotency_body = {"label": req.label}
    replay = await idempotency.replay_or_none(
        user.client_id, "POST /api/v1/settings/api-keys", request, idempotency_body
    )
    if replay is not None:
        return replay

    try:
        result = await db_manager.generate_api_key(
            user.client_id, req.label, created_by_user_id=user.user_id,
        )
    except Exception as e:
        logger.error(f"Failed to create API key for tenant '{user.client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to create API key right now.")

    await idempotency.store(
        user.client_id, "POST /api/v1/settings/api-keys", request, idempotency_body, 200, result
    )
    return result


@router.get("/api/v1/settings/api-keys", tags=["Settings"])
async def list_api_keys(
    user: AuthenticatedUser = Depends(require_role("owner", "admin")),
):
    try:
        return {"api_keys": await db_manager.list_api_keys(user.client_id)}
    except Exception as e:
        logger.error(f"Failed to list API keys for tenant '{user.client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to load API keys right now.")


@router.delete("/api/v1/settings/api-keys/{key_id}", tags=["Settings"])
async def revoke_api_key(
    key_id: int,
    user: AuthenticatedUser = Depends(require_role("owner", "admin")),
):
    try:
        revoked = await db_manager.revoke_api_key(user.client_id, key_id)
    except Exception as e:
        logger.error(f"Failed to revoke API key {key_id} for tenant '{user.client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to revoke API key right now.")
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found, already revoked, or not owned by this tenant.")
    return {"revoked": True, "key_id": key_id}
