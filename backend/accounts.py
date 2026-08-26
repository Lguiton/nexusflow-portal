"""
RBAC-01: real account management -- signup, login, and per-tenant team
management. Replaces /api/v1/auth/dev-login (see main.py -- that endpoint
is now removed, not just deprecated, per its own comment: "must be
replaced, not just left in place").

Role model (owner/admin/member/viewer) is enforced here via
backend.auth.require_role; db_manager.py owns the actual storage and
enforces tenant isolation (every query is scoped by client_id) so a bug
here can be authorization-wrong at worst, never cross-tenant-data-wrong.
"""
import logging
import re
import secrets
import string
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator

try:
    from backend import db_manager
    from backend.auth import (
        AuthenticatedUser,
        JWT_SECRET,
        JWT_ALGORITHM,
        hash_password,
        verify_password,
        require_role,
        verify_jwt_and_get_user,
        sanitize_client_id,
    )
except ImportError:
    from backend import db_manager  # type: ignore
    from auth import (  # type: ignore
        AuthenticatedUser,
        JWT_SECRET,
        JWT_ALGORITHM,
        hash_password,
        verify_password,
        require_role,
        verify_jwt_and_get_user,
        sanitize_client_id,
    )

router = APIRouter()
logger = logging.getLogger("eivanta.accounts")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOKEN_TTL_HOURS = 12


def _mint_token(user: dict) -> str:
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server authentication is not configured (JWT_SECRET unset).")
    now = datetime.now(timezone.utc)
    payload = {
        "client_id": user["client_id"],
        "user_id": user["user_id"],
        "email": user["email"],
        "role": user["role"],
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _slugify_client_id(company_name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", company_name.strip()).strip("-").upper()[:40] or "TENANT"
    suffix = "".join(secrets.choice(string.digits) for _ in range(4))
    return sanitize_client_id(f"{base}-{suffix}")


def _generate_temp_password() -> str:
    # 16 chars from a mixed alphabet, cryptographically random -- this is
    # NEVER emailed in this router; see db_manager.create_invited_user's
    # caller in the /api/v1/team/invite endpoint below for how it's
    # actually handed to the invited teammate (returned once in the API
    # response until the Resend email integration lands -- see the Phase
    # 6+ report for that follow-up).
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


class SignupRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v.strip()):
            raise ValueError("must be a valid email address")
        return v.strip().lower()


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class InviteRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    role: str = Field(...)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v.strip()):
            raise ValueError("must be a valid email address")
        return v.strip().lower()

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in ("owner", "admin", "member", "viewer"):
            raise ValueError("role must be one of: owner, admin, member, viewer")
        return v


class UpdateRoleRequest(BaseModel):
    role: str = Field(...)

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in ("owner", "admin", "member", "viewer"):
            raise ValueError("role must be one of: owner, admin, member, viewer")
        return v


@router.post("/api/v1/auth/signup")
async def signup(req: SignupRequest):
    """
    Creates a brand-new tenant and its first user (always role='owner').
    client_id is generated from company_name rather than asked of the
    signer directly -- one less thing to get wrong/collide on, and it
    keeps the same CLI-style identifier shape the rest of the codebase
    already assumes (see sanitize_client_id).
    """
    client_id = _slugify_client_id(req.company_name)
    pw_hash = hash_password(req.password)
    try:
        user = await db_manager.create_tenant_and_owner(client_id, req.company_name.strip(), req.email, pw_hash)
    except db_manager.DuplicateEmailError:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    except db_manager.TenantExistsError:
        # Extremely unlikely given the random suffix, but not impossible --
        # surface it as a clean 409 rather than a raw 500 if it ever does.
        raise HTTPException(status_code=409, detail="Could not allocate a unique account -- please try again.")
    except Exception as e:
        logger.error(f"Signup failed for email '{req.email}': {e}")
        raise HTTPException(status_code=502, detail="Unable to create your account right now.")

    token = _mint_token(user)
    return {"access_token": token, "token_type": "bearer", **user}


@router.post("/api/v1/auth/login")
async def login(req: LoginRequest):
    email_norm = req.email.strip().lower()
    user = await db_manager.get_user_by_email(email_norm)
    # Deliberately identical error/timing shape whether the email doesn't
    # exist at all or the password is wrong -- verify_password still runs
    # against a real (if unrelated) hash in the not-found case below, so
    # this doesn't hand an attacker a free "which emails have accounts"
    # oracle via response time either.
    dummy_hash = "$2b$12$C6UzMDM.H6dfI/f8IjOhFO/nUXFrjJc3cJKxk9nqPB2Rjz2j1J.Rm"
    password_ok = verify_password(req.password, user["password_hash"] if user else dummy_hash)
    if not user or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    await db_manager.update_last_login(user["user_id"])
    token = _mint_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user["user_id"],
        "client_id": user["client_id"],
        "email": user["email"],
        "role": user["role"],
    }


@router.get("/api/v1/auth/me")
async def get_me(user: AuthenticatedUser = Depends(verify_jwt_and_get_user)):
    return {"user_id": user.user_id, "client_id": user.client_id, "email": user.email, "role": user.role}


@router.get("/api/v1/team/users")
async def list_team(user: AuthenticatedUser = Depends(verify_jwt_and_get_user)):
    """Any authenticated teammate (any role) can see the team roster -- not a sensitive operation on its own."""
    return {"users": await db_manager.list_users_for_tenant(user.client_id)}


@router.post("/api/v1/team/invite")
async def invite_teammate(
    req: InviteRequest,
    user: AuthenticatedUser = Depends(require_role("owner", "admin")),
):
    temp_password = _generate_temp_password()
    pw_hash = hash_password(temp_password)
    try:
        invited = await db_manager.create_invited_user(user.client_id, req.email, pw_hash, req.role)
    except db_manager.DuplicateEmailError:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    except db_manager.TenantExistsError:
        # Shouldn't happen -- user.client_id came from a verified token for
        # an already-real tenant -- but fail loudly rather than silently if it ever does.
        raise HTTPException(status_code=500, detail="Your own tenant record could not be found.")
    except Exception as e:
        logger.error(f"Invite failed for email '{req.email}' on tenant '{user.client_id}': {e}")
        raise HTTPException(status_code=502, detail="Unable to invite that teammate right now.")

    # TEMPORARY: returns the temp password in the API response so the
    # inviter can hand it over manually. Once the Resend email integration
    # lands (see the Phase 6+ report's next-stage task), this should email
    # the invited teammate directly instead and stop returning it here --
    # tracked, not silently forgotten.
    return {**invited, "temp_password": temp_password}


@router.patch("/api/v1/team/users/{target_user_id}/role")
async def update_teammate_role(
    target_user_id: int,
    req: UpdateRoleRequest,
    user: AuthenticatedUser = Depends(require_role("owner")),
):
    if target_user_id == user.user_id and req.role != "owner":
        raise HTTPException(status_code=400, detail="You can't demote your own account -- have another owner do it.")
    updated = await db_manager.update_user_role(user.client_id, target_user_id, req.role)
    if not updated:
        raise HTTPException(status_code=404, detail="No matching teammate found on your tenant.")
    return {"user_id": target_user_id, "role": req.role, "updated": True}


@router.delete("/api/v1/team/users/{target_user_id}")
async def remove_teammate(
    target_user_id: int,
    user: AuthenticatedUser = Depends(require_role("owner")),
):
    if target_user_id == user.user_id:
        raise HTTPException(status_code=400, detail="You can't remove your own account -- have another owner do it.")
    removed = await db_manager.remove_user(user.client_id, target_user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="No matching teammate found on your tenant.")
    return {"user_id": target_user_id, "removed": True}
