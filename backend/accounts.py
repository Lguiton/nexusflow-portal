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
import base64
import hashlib
import io
import logging
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt as pyjwt
import pyotp
import qrcode
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, field_validator

try:
    from backend import db_manager
    from backend.auth import (
        AuthenticatedUser,
        MfaChallenge,
        JWT_SECRET,
        JWT_ALGORITHM,
        hash_password,
        verify_password,
        require_role,
        require_role_allow_suspended,
        verify_jwt_and_get_user,
        verify_jwt_and_get_user_allow_suspended,
        verify_mfa_challenge_token,
        sanitize_client_id,
    )
    from backend.byok import encrypt_secret, decrypt_secret
except ImportError:
    from backend import db_manager  # type: ignore
    from auth import (  # type: ignore
        AuthenticatedUser,
        MfaChallenge,
        JWT_SECRET,
        JWT_ALGORITHM,
        hash_password,
        verify_password,
        require_role,
        require_role_allow_suspended,
        verify_jwt_and_get_user,
        verify_jwt_and_get_user_allow_suspended,
        verify_mfa_challenge_token,
        sanitize_client_id,
    )
    from byok import encrypt_secret, decrypt_secret  # type: ignore

router = APIRouter()
logger = logging.getLogger("eivanta.accounts")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# AUTH-02: access tokens are now SHORT-lived (this used to be a 12-hour
# JWT with no way to revoke it early -- a stolen token was live for up to
# half a day no matter what). A stateless JWT still can't be revoked mid-
# flight, so the fix is to make one expire quickly instead; real sessions
# stay signed in via the refresh token below, rotated on every use (see
# REFRESH_TOKEN_TTL_DAYS and refresh() further down). The frontend must
# proactively refresh before this expires -- see ClientContext.tsx's
# background refresh timer, which refreshes well inside this window
# rather than waiting for a 401.
TOKEN_TTL_MINUTES = 30
# The long-lived credential. Opaque (not a JWT -- see _mint_refresh_token),
# stored here only as a SHA-256 hash, single-use in practice because every
# successful /api/v1/auth/refresh call rotates it (see refresh() below).
REFRESH_TOKEN_TTL_DAYS = 30

# AUTH-05: login throttling / brute-force protection. Module-level named
# constants (not magic numbers inline in login() below) so they read live
# from here into the Assumption Ledger (backend/assumptions.py), same
# disclosure pattern as virtual_cfo.ASSUMED_CASH_RESERVES and
# predictive_forecaster.MIN_PERIODS_FOR_FORECAST -- a security policy this
# concrete deserves to be a documented, inspectable number, not a value
# buried in a conditional.
#
# 5 attempts / 15-minute lockout is a common, moderate default (stricter
# than e.g. a generous 10-attempt policy, looser than a punitive 3-attempt
# one) -- picked as a reasonable starting point, not derived from this
# product's own real login-abuse data (none exists yet). Revisit once
# there's real attack-traffic history to tune against.
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15

# AUTH-04: TOTP-based MFA. Authenticator-app only (RFC 6238) -- no SMS/
# email second factor, so this isn't blocked on the founder's still-
# pending email/SMS provider accounts. Same disclosure-as-named-constant
# pattern as MAX_FAILED_LOGIN_ATTEMPTS above.
MFA_ISSUER_NAME = "Eivanta"
MFA_CHALLENGE_TTL_MINUTES = 5
MFA_BACKUP_CODE_COUNT = 8
# Reuses the SAME brute-force counters AUTH-05 already put on `users`
# (failed_login_attempts/locked_until) for a wrong MFA code, not a
# parallel set of columns -- by the time someone reaches /mfa/verify
# they've already proven they know the password, but a 6-digit TOTP code
# is still guessable in bulk without a real attempt limit, so this stays
# one unified "prove you're the account holder" lockout rather than two
# separate, easier-to-miss ones.


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
        "exp": now + timedelta(minutes=TOKEN_TTL_MINUTES),
        # AUTH-06 found this one real, if minor, gap: with no jti, two
        # access tokens minted for the same user in the same second (e.g.
        # a signup immediately followed by a refresh, in a fast test or a
        # fast client) are byte-for-byte IDENTICAL, since every other claim
        # here is also identical at second resolution. A random jti makes
        # every mint unique regardless of timing, which is also just
        # standard JWT practice independent of this bug.
        "jti": secrets.token_urlsafe(16),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _hash_refresh_token(raw: str) -> str:
    """SHA-256, same reasoning as _hash_backup_code below -- a high-entropy random token, not a human-chosen secret."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _mint_refresh_token(
    user: dict, replaces_hash: Optional[str] = None, device_label: Optional[str] = None
) -> str:
    """
    AUTH-02: generates a new opaque refresh token, stores only its SHA-256
    hash (via db_manager.create_refresh_token), and returns the RAW value
    to hand to the client -- this is the one place that raw value exists
    outside the client itself; it is never logged or persisted anywhere.
    `replaces_hash`, when set, is the hash of the token this one is
    rotating away from (see refresh() below).

    AUTH-06: `device_label`, when given, is only actually USED by
    db_manager.create_refresh_token on a FRESH mint (replaces_hash is
    None) -- a rotation (refresh()) carries the OLD row's label forward
    instead and ignores whatever's passed here, so callers don't need to
    care which case they're in; only signup/login/mfa_verify below ever
    pass a real value.
    """
    raw = secrets.token_urlsafe(48)
    token_hash = _hash_refresh_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_TTL_DAYS)
    await db_manager.create_refresh_token(
        user["user_id"], user["client_id"], token_hash, expires_at,
        replaces_hash=replaces_hash, device_label=device_label,
    )
    return raw


# AUTH-06: lightweight, dependency-free User-Agent -> human label heuristic.
# Not meant to be a precise device fingerprint (no library, no client hints)
# -- just enough for someone reviewing their own session list to recognize
# "oh, that's my laptop" vs. "I don't recognize this one." Order matters:
# Edge and Opera's UA strings both also contain "Chrome/", and Safari's
# contains "Safari/" even on Chrome, so the more specific checks must run
# first or every Edge/Opera/Chrome session would misreport as Chrome/Safari.
def _derive_device_label(user_agent: Optional[str]) -> Optional[str]:
    if not user_agent:
        return None
    ua = user_agent
    # Mobile checks MUST run before the desktop-OS checks below: a real
    # iOS Safari UA literally contains the substring "like Mac OS X" (a
    # long-standing iOS compatibility convention), and Android UAs contain
    # "Linux" -- so checking "Mac OS X"/"Linux" first would misreport
    # every iPhone as macOS and every Android device as Linux.
    if "Android" in ua:
        os_label = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        os_label = "iOS"
    elif "Windows" in ua:
        os_label = "Windows"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_label = "macOS"
    elif "Linux" in ua:
        os_label = "Linux"
    else:
        os_label = None

    if "Edg/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "Chrome/" in ua:
        browser = "Chrome"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Safari/" in ua:
        browser = "Safari"
    else:
        browser = None

    if browser and os_label:
        return f"{browser} on {os_label}"
    if browser or os_label:
        return browser or os_label
    # Unrecognized UA shape (e.g. a script/API client) -- fall back to a
    # truncated raw string rather than silently storing nothing.
    return ua.strip()[:80] or None


def _mint_mfa_challenge_token(user: dict) -> str:
    """
    AUTH-04: a SEPARATE, short-lived (5 min) token minted by login() when
    an account has MFA enabled, instead of a real access token. Carries
    the same identity claims a real token would (so verify_mfa_challenge_
    token can resolve who's completing the challenge without a second DB
    round-trip), plus mfa_challenge=True -- the one claim
    backend/auth.py's real-token dependencies explicitly reject, so this
    can never be used as a substitute for actually passing the second
    factor.
    """
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server authentication is not configured (JWT_SECRET unset).")
    now = datetime.now(timezone.utc)
    payload = {
        "client_id": user["client_id"],
        "user_id": user["user_id"],
        "email": user["email"],
        "role": user["role"],
        "mfa_challenge": True,
        "iat": now,
        "exp": now + timedelta(minutes=MFA_CHALLENGE_TTL_MINUTES),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _hash_backup_code(code: str) -> str:
    """SHA-256, not bcrypt -- these are high-entropy random codes, not human-chosen passwords (see api_keys.py's key_hash for the same reasoning)."""
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def _generate_backup_codes(n: int) -> list:
    """Real codes, cryptographically random, formatted XXXX-XXXX for readability. Returned in plaintext ONCE by /mfa/enable -- only their hashes are ever persisted."""
    alphabet = string.ascii_uppercase + string.digits
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(alphabet) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


async def _verify_totp_or_backup_code(user_id: int, code: str) -> bool:
    """
    Shared by /mfa/verify (completing a login) and /mfa/disable (proving
    you still control this factor before turning it off). Tries a real
    TOTP code first (valid_window=1 tolerates the submitter's clock being
    up to one 30s step off in either direction -- pyotp's own documented
    mechanism for this, not a hand-rolled fudge factor), then falls back
    to a backup code. A backup code match CONSUMES it (single-use) --
    checked here, not by the caller, so every call site gets that
    guarantee for free.
    """
    encrypted_secret = await db_manager.get_mfa_secret_encrypted(user_id)
    if not encrypted_secret:
        return False
    code_clean = (code or "").strip().replace(" ", "")
    try:
        secret = decrypt_secret(encrypted_secret)
        if pyotp.TOTP(secret).verify(code_clean, valid_window=1):
            return True
    except Exception as e:
        logger.error(f"MFA TOTP verification raised for user_id {user_id}: {e}")
    return await db_manager.consume_backup_code_if_valid(user_id, _hash_backup_code(code_clean))


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


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1, max_length=512)


class LogoutRequest(BaseModel):
    # Optional -- logging out with no refresh token (or an already-
    # invalid one) is still a valid call, it just has nothing server-side
    # to revoke. See logout()'s own docstring for why this always 200s.
    refresh_token: Optional[str] = Field(default=None, max_length=512)


class MfaEnableRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


class MfaDisableRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=6, max_length=9)


class MfaVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=9)


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


class TenantDeleteRequest(BaseModel):
    # TEN-03: real, permanent, cascading delete -- requiring the caller to
    # re-type the tenant's own company_name is a deliberate speed bump
    # against an accidental click, the same real-world pattern GitHub/AWS
    # use for their own "type the resource name to confirm" delete flows.
    # Not a security boundary (require_role_allow_suspended("owner") is
    # that) -- purely a mistake-prevention one.
    confirm_company_name: str = Field(..., min_length=1, max_length=200)


async def _lifecycle_fields(client_id: str) -> dict:
    """
    Shared by signup/login/me below so every auth response carries the
    SAME two fields (lifecycle_status, tenant_suspended) in the same
    shape -- the frontend only has to check one place regardless of which
    call just ran. A brand-new signup's tenant is always 'active' (just
    created); a returning login/me call reflects whatever an owner has
    since set via /api/v1/tenant/suspend.
    """
    status = await db_manager.get_tenant_lifecycle_status(client_id)
    status = status or "active"
    return {"lifecycle_status": status, "tenant_suspended": status == "suspended"}


@router.post("/api/v1/auth/signup")
async def signup(req: SignupRequest, request: Request):
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
    device_label = _derive_device_label(request.headers.get("user-agent"))
    refresh_token = await _mint_refresh_token(user, device_label=device_label)
    return {
        "access_token": token, "refresh_token": refresh_token, "token_type": "bearer",
        **user, **await _lifecycle_fields(user["client_id"]),
    }


@router.post("/api/v1/auth/login")
async def login(req: LoginRequest, request: Request):
    email_norm = req.email.strip().lower()
    user = await db_manager.get_user_by_email(email_norm)

    # AUTH-05: check an existing lockout BEFORE ever calling
    # verify_password. A nonexistent email has no user row and therefore
    # no locked_until to check -- it always falls through to the normal
    # wrong-password path below, so this lockout check can never be used
    # to distinguish "this email doesn't exist" from "this email exists
    # but isn't locked." It CAN reveal "this specific email exists" once
    # it's locked (a 429 instead of a 401) -- a real, disclosed trade-off,
    # not an oversight: every mainstream login system (GitHub, Google,
    # etc.) makes the same call, because by the time an account is
    # actually locked, an attacker has already sent enough failed
    # attempts against that one email to have a strong signal it's real
    # regardless of what this endpoint says next.
    if user and user["locked_until"] is not None:
        from datetime import datetime, timezone
        locked_until = user["locked_until"]
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > datetime.now(timezone.utc):
            minutes_left = max(1, int((locked_until - datetime.now(timezone.utc)).total_seconds() // 60) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed login attempts. Try again in about {minutes_left} minute{'s' if minutes_left != 1 else ''}.",
            )

    # Deliberately identical error/timing shape whether the email doesn't
    # exist at all or the password is wrong -- verify_password still runs
    # against a real (if unrelated) hash in the not-found case below, so
    # this doesn't hand an attacker a free "which emails have accounts"
    # oracle via response time either.
    dummy_hash = "$2b$12$C6UzMDM.H6dfI/f8IjOhFO/nUXFrjJc3cJKxk9nqPB2Rjz2j1J.Rm"
    password_ok = verify_password(req.password, user["password_hash"] if user else dummy_hash)
    if not user or not password_ok:
        if user:
            # AUTH-05: only a REAL user row can accumulate failed attempts
            # -- a nonexistent email has nothing to increment, so this
            # never fires for an unknown address (see the module-level
            # comment above on why that matters for enumeration).
            result = await db_manager.record_failed_login(
                user["user_id"], MAX_FAILED_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_MINUTES
            )
            if result["locked"]:
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many failed login attempts. Try again in about {LOGIN_LOCKOUT_MINUTES} minutes.",
                )
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # AUTH-04: password verified, but this account has a second factor --
    # do NOT mint a real access token or reset the login-throttle counter
    # yet. Both are deferred to a successful /api/v1/auth/mfa/verify call,
    # so "logged in" keeps meaning "password AND MFA both passed," not
    # just the first of the two.
    if user["mfa_enabled"]:
        challenge_token = _mint_mfa_challenge_token(user)
        return {"mfa_required": True, "mfa_challenge_token": challenge_token}

    await db_manager.update_last_login(user["user_id"])
    token = _mint_token(user)
    device_label = _derive_device_label(request.headers.get("user-agent"))
    refresh_token = await _mint_refresh_token(user, device_label=device_label)
    return {
        "access_token": token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user_id": user["user_id"],
        "client_id": user["client_id"],
        "email": user["email"],
        "role": user["role"],
        **await _lifecycle_fields(user["client_id"]),
    }


@router.post("/api/v1/auth/mfa/verify")
async def mfa_verify(
    req: MfaVerifyRequest,
    request: Request,
    challenge: MfaChallenge = Depends(verify_mfa_challenge_token),
):
    """
    AUTH-04 step 2 of a login for an MFA-enabled account. Reuses the SAME
    lockout state login() itself checks (failed_login_attempts/
    locked_until) -- a real code is checked against the SAME "prove
    you're the account holder" budget a wrong password would have spent,
    not a separate, easier-to-bypass counter. Returns the exact same
    response shape a normal (non-MFA) login does, so the frontend applies
    it identically either way.
    """
    user = await db_manager.get_user_by_id(challenge.user_id, challenge.client_id)
    if not user:
        raise HTTPException(status_code=401, detail="Your account could not be found -- please log in again.")

    if user["locked_until"] is not None:
        locked_until = user["locked_until"]
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > datetime.now(timezone.utc):
            minutes_left = max(1, int((locked_until - datetime.now(timezone.utc)).total_seconds() // 60) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in about {minutes_left} minute{'s' if minutes_left != 1 else ''}.",
            )

    if not await _verify_totp_or_backup_code(user["user_id"], req.code):
        result = await db_manager.record_failed_login(user["user_id"], MAX_FAILED_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_MINUTES)
        if result["locked"]:
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in about {LOGIN_LOCKOUT_MINUTES} minutes.",
            )
        raise HTTPException(status_code=401, detail="Incorrect verification code.")

    await db_manager.update_last_login(user["user_id"])
    token = _mint_token(user)
    device_label = _derive_device_label(request.headers.get("user-agent"))
    refresh_token = await _mint_refresh_token(user, device_label=device_label)
    return {
        "access_token": token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user_id": user["user_id"],
        "client_id": user["client_id"],
        "email": user["email"],
        "role": user["role"],
        **await _lifecycle_fields(user["client_id"]),
    }


@router.post("/api/v1/auth/refresh")
async def refresh(req: RefreshRequest):
    """
    AUTH-02: exchanges a valid, not-yet-used refresh token for a brand new
    access token AND a brand new refresh token (rotation -- the presented
    one is immediately retired, whether or not this call succeeds past
    this point). No Authorization header is read here; possessing a valid
    refresh token IS the credential this endpoint checks, the same way a
    password is the credential /login checks.
    """
    token_hash = _hash_refresh_token(req.refresh_token.strip())
    stored = await db_manager.get_refresh_token(token_hash)
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid refresh token -- please log in again.")

    if stored["revoked_at"] is not None:
        # AUTH-06 found a real bug in this check's original form (a bare
        # "revoked_at is not None -> nuke everything"): that treated ANY
        # revoked row as a stolen-token signal, but revoked_at is now also
        # set by three entirely legitimate, non-compromise actions --
        # logout(), DELETE /api/v1/auth/sessions/{id}, and revoke-all --
        # none of which mean "this token was copied." A device an admin
        # (or the user, from another device) had just signed out would
        # hit this branch on its next ordinary background refresh and end
        # up nuking every OTHER session on the account too, which is
        # exactly backwards for a feature whose whole point is "sign out
        # this one device without disturbing the rest."
        #
        # replaced_by_hash is what actually distinguishes the two cases:
        # it is set ONLY by a real rotation (create_refresh_token sets it
        # on the old row in the same call that mints the row replacing
        # it -- see refresh()'s own success path below), never by
        # logout/session-delete/revoke-all. So a replay of a token that
        # has replaced_by_hash set is the genuine "this exact credential
        # was used twice" signal reuse-detection exists to catch; a
        # revoked token with no replaced_by_hash is just "this session
        # was already ended on purpose," and gets a plain 401 with no
        # side effects on the account's other sessions.
        if stored["replaced_by_hash"] is not None:
            await db_manager.revoke_all_refresh_tokens_for_user(stored["user_id"])
            logger.warning(f"Refresh token reuse detected for user_id {stored['user_id']} -- all sessions revoked.")
            raise HTTPException(
                status_code=401,
                detail="This session was revoked for your security -- please log in again.",
            )
        raise HTTPException(
            status_code=401,
            detail="This session has ended -- please log in again.",
        )

    expires_at = stored["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Your session has expired -- please log in again.")

    user = await db_manager.get_user_by_id(stored["user_id"], stored["client_id"])
    if not user:
        raise HTTPException(status_code=401, detail="Your account could not be found -- please log in again.")

    await db_manager.revoke_refresh_token(token_hash)
    new_refresh_token = await _mint_refresh_token(user, replaces_hash=token_hash)
    new_access_token = _mint_token(user)
    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "user_id": user["user_id"],
        "client_id": user["client_id"],
        "email": user["email"],
        "role": user["role"],
        **await _lifecycle_fields(user["client_id"]),
    }


@router.post("/api/v1/auth/logout")
async def logout(req: LogoutRequest):
    """
    Revokes ONE refresh token -- the one this device/session was using --
    so it (and any future rotation attempt with it) can never mint a new
    access token again. The access token already in the caller's hands
    still technically works until it naturally expires (a stateless JWT
    can't be revoked early without a much bigger blocklist mechanism this
    app doesn't have), but that window is now only TOKEN_TTL_MINUTES long
    instead of the old 12 hours.

    Deliberately needs no Authorization header and always returns 200
    whether the token was found, already revoked, or missing entirely --
    an access token may well already be expired by the time someone
    clicks "log out," and distinguishing "that token doesn't exist" from
    "that token was already revoked" in the response has no legitimate use
    and only helps an attacker probe.
    """
    if req.refresh_token:
        token_hash = _hash_refresh_token(req.refresh_token.strip())
        await db_manager.revoke_refresh_token(token_hash)
    return {"ok": True}


@router.get("/api/v1/auth/sessions")
async def list_sessions(user: AuthenticatedUser = Depends(verify_jwt_and_get_user)):
    """
    AUTH-06: every currently-active (non-revoked, non-expired) refresh-
    token chain for the CALLING user only -- see
    db_manager.list_active_sessions_for_user's own docstring for why
    token_hash itself never leaves that function. There's no reliable way
    for this endpoint to know which returned row corresponds to the
    request's own current session (the access token carries no link back
    to the refresh-token row that ultimately minted it), so it doesn't try
    to flag one as "this device" -- the frontend can only offer "sign out
    this device" via a real per-session revoke, not a highlighted current
    one. See revoke_all_sessions below for the coarser "sign out
    everywhere, including here" alternative that sidesteps this.
    """
    sessions = await db_manager.list_active_sessions_for_user(user.user_id)
    return {"sessions": sessions}


@router.delete("/api/v1/auth/sessions/{session_id}")
async def revoke_session(session_id: int, user: AuthenticatedUser = Depends(verify_jwt_and_get_user)):
    """
    AUTH-06: signs out ONE specific device/session by id, without touching
    any of the caller's other sessions. Scoped to the caller's own user_id
    inside db_manager.revoke_session_for_user -- this is what makes it safe
    to take session_id straight from the URL with no extra ownership check
    here. 404s (not 403) on someone else's session id, an already-revoked
    one, or a made-up id -- all three are deliberately indistinguishable to
    the caller.
    """
    revoked = await db_manager.revoke_session_for_user(user.user_id, session_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="No matching active session found.")
    return {"session_id": session_id, "revoked": True}


@router.post("/api/v1/auth/sessions/revoke-all")
async def revoke_all_sessions(user: AuthenticatedUser = Depends(verify_jwt_and_get_user)):
    """
    AUTH-06: the blunt "I think my account is compromised" tool -- revokes
    EVERY refresh token on the account, including the one backing the
    session making this very call. Deliberately reuses AUTH-02's existing
    revoke_all_refresh_tokens_for_user (the same function reuse-detection
    on /auth/refresh already calls) rather than adding a second code path
    for "revoke everything." A more surgical "sign out every device except
    this one" was considered and dropped for this pass: the access token
    making this call has no clean, existing link back to which specific
    refresh-token row minted it, so "except this one" can't be done
    correctly without adding that link first -- tracked as a real gap, not
    silently assumed away. The caller's own current access token still
    works until it naturally expires (same limitation logout() already
    documents), so the frontend should immediately clear local auth state
    and treat this like a logout, not rely on the access token dying here.
    """
    await db_manager.revoke_all_refresh_tokens_for_user(user.user_id)
    return {"ok": True}


@router.post("/api/v1/auth/mfa/setup")
async def mfa_setup(user: AuthenticatedUser = Depends(verify_jwt_and_get_user)):
    """
    AUTH-04 step 1: generates a fresh TOTP secret and stores it as PENDING
    (never active until confirmed by a real code via /mfa/enable -- see
    db_manager.set_pending_mfa_secret's own docstring for why this stays
    separate from an already-working active secret). Safe to call again
    to restart enrollment (e.g. scanned the QR with the wrong app) -- it
    just overwrites the still-pending secret; an already-ENABLED account
    calling this is re-enrolling a new device, and stays protected by its
    OLD secret until the new one is confirmed.

    Returns the raw secret (for manual entry) and a QR code as a PNG data
    URI, rendered server-side (qrcode[pil]) so the frontend needs no new
    QR-rendering dependency of its own.
    """
    secret = pyotp.random_base32()
    encrypted = encrypt_secret(secret)
    await db_manager.set_pending_mfa_secret(user.user_id, encrypted)

    otpauth_uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=MFA_ISSUER_NAME)
    qr_img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    return {"secret": secret, "otpauth_uri": otpauth_uri, "qr_code_data_uri": qr_data_uri}


@router.post("/api/v1/auth/mfa/enable")
async def mfa_enable(
    req: MfaEnableRequest,
    user: AuthenticatedUser = Depends(verify_jwt_and_get_user),
):
    """
    AUTH-04 step 2: confirms enrollment with a real code from the
    authenticator app, generates real backup codes (shown ONCE, here,
    in plaintext -- only their hashes are ever persisted), and moves the
    pending secret to active.
    """
    pending_encrypted = await db_manager.get_pending_mfa_secret(user.user_id)
    if not pending_encrypted:
        raise HTTPException(status_code=400, detail="No pending MFA enrollment -- call /api/v1/auth/mfa/setup first.")
    try:
        pending_secret = decrypt_secret(pending_encrypted)
    except Exception as e:
        logger.error(f"MFA pending-secret decrypt failed for user_id {user.user_id}: {e}")
        raise HTTPException(status_code=502, detail="Could not verify your enrollment right now -- please try /mfa/setup again.")

    if not pyotp.TOTP(pending_secret).verify(req.code.strip().replace(" ", ""), valid_window=1):
        raise HTTPException(status_code=400, detail="Incorrect code -- check your authenticator app and try again.")

    backup_codes = _generate_backup_codes(MFA_BACKUP_CODE_COUNT)
    backup_code_hashes = [_hash_backup_code(c) for c in backup_codes]
    confirmed = await db_manager.confirm_mfa_enrollment(user.user_id, backup_code_hashes)
    if not confirmed:
        # Pending secret vanished between the two reads above (e.g. a
        # concurrent /mfa/setup call from another tab) -- real, if rare.
        raise HTTPException(status_code=409, detail="Your enrollment changed before this could be confirmed -- please try /mfa/setup again.")

    return {"enabled": True, "backup_codes": backup_codes}


@router.post("/api/v1/auth/mfa/disable")
async def mfa_disable(
    req: MfaDisableRequest,
    user: AuthenticatedUser = Depends(verify_jwt_and_get_user),
):
    """
    Requires BOTH the current password AND a valid code (TOTP or backup)
    before turning MFA off -- a bare authenticated session (e.g. a
    hijacked browser tab) is deliberately not enough on its own to remove
    someone's second factor.
    """
    full_user = await db_manager.get_user_by_id(user.user_id, user.client_id)
    if not full_user:
        raise HTTPException(status_code=404, detail="Your account could not be found.")
    if not verify_password(req.password, full_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    if not full_user["mfa_enabled"]:
        raise HTTPException(status_code=400, detail="MFA is not currently enabled on your account.")
    if not await _verify_totp_or_backup_code(user.user_id, req.code):
        raise HTTPException(status_code=400, detail="Incorrect verification code.")

    await db_manager.disable_mfa(user.user_id)
    return {"enabled": False}


@router.get("/api/v1/auth/mfa/status")
async def mfa_status(user: AuthenticatedUser = Depends(verify_jwt_and_get_user)):
    """Any authenticated person can check their OWN MFA status -- this never takes a user_id parameter, only ever the caller's own."""
    return await db_manager.get_mfa_status(user.user_id)


@router.get("/api/v1/auth/me")
async def get_me(user: AuthenticatedUser = Depends(verify_jwt_and_get_user_allow_suspended)):
    """
    TEN-01/TEN-02: deliberately uses the _allow_suspended dependency, NOT
    verify_jwt_and_get_user -- this is the one call ClientContext.tsx makes
    on every page load to restore a session (see restoreSession there). If
    this were gated on suspension too, a suspended tenant's frontend would
    see a bare 423 on the very call it uses to decide whether to render
    the app at all, with no way to distinguish "suspended" from "your
    token expired, please log in again." Returning tenant_suspended here
    explicitly is what lets AuthGate.tsx show a real "Account Suspended"
    screen instead of silently bouncing back to the login form.
    """
    return {
        "user_id": user.user_id, "client_id": user.client_id, "email": user.email, "role": user.role,
        **await _lifecycle_fields(user.client_id),
    }


@router.get("/api/v1/tenant/status")
async def tenant_status(user: AuthenticatedUser = Depends(verify_jwt_and_get_user_allow_suspended)):
    """Any authenticated role can see the tenant's own lifecycle state -- not sensitive on its own, and every role needs it to render the right UI."""
    detail = await db_manager.get_tenant_lifecycle_detail(user.client_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Your tenant record could not be found.")
    return detail


@router.post("/api/v1/tenant/suspend")
async def suspend_tenant(user: AuthenticatedUser = Depends(require_role_allow_suspended("owner"))):
    """
    TEN-01/TEN-02: manual, owner-only, self-service suspension -- NOT
    subscription-driven (no billing exists yet; see this item's own note
    in the Master Build List on why that half stays open). Uses the
    _allow_suspended variant so this is idempotent even if somehow called
    on an already-suspended tenant (see suspend_tenant's own docstring in
    db_manager.py).
    """
    detail = await db_manager.suspend_tenant(user.client_id, user.user_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Your tenant record could not be found.")
    return detail


@router.post("/api/v1/tenant/reactivate")
async def reactivate_tenant(user: AuthenticatedUser = Depends(require_role_allow_suspended("owner"))):
    """
    TEN-01/TEN-02: the ONE endpoint that MUST work while the tenant is
    suspended, or an owner who suspends their own account would have no
    way back in. require_role_allow_suspended("owner") is exactly that:
    role-gated, but never itself blocked by the suspension gate.
    """
    detail = await db_manager.reactivate_tenant(user.client_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Your tenant record could not be found.")
    return detail


@router.get("/api/v1/tenant/export")
async def export_tenant(user: AuthenticatedUser = Depends(require_role_allow_suspended("owner", "admin"))):
    """
    TEN-03: real data-portability export -- every row this tenant owns,
    across every tenant-scoped table (see db_manager._TENANT_SCOPED_TABLES),
    minus secret columns (password hashes, API key hashes). Owner/admin,
    same gating as BYOK settings -- and deliberately reachable even while
    suspended, since a suspended tenant should still be able to get its own
    data out.
    """
    data = await db_manager.export_tenant_data(user.client_id)
    if not data:
        raise HTTPException(status_code=404, detail="Your tenant record could not be found.")
    return data


@router.delete("/api/v1/tenant")
async def delete_tenant(
    req: TenantDeleteRequest,
    user: AuthenticatedUser = Depends(require_role_allow_suspended("owner")),
):
    """
    TEN-03: real, permanent, cascading delete of this tenant and every row
    it owns (see db_manager.delete_tenant_permanently). Requires the
    caller to re-type the tenant's real company_name as a mistake-
    prevention speed bump (see TenantDeleteRequest's own docstring) --
    checked here, not in db_manager, so the storage layer stays a pure
    "delete unconditionally" primitive with exactly one caller that can
    skip confirmation, and it isn't this one. After this succeeds, the
    caller's own JWT is for a tenant that no longer exists -- the frontend
    is responsible for discarding it (logout) rather than this endpoint
    trying to invalidate a stateless JWT server-side.
    """
    detail = await db_manager.get_tenant_lifecycle_detail(user.client_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Your tenant record could not be found.")
    if req.confirm_company_name.strip() != (detail["company_name"] or "").strip():
        raise HTTPException(
            status_code=400,
            detail="confirm_company_name did not match this tenant's real company name -- nothing was deleted.",
        )
    result = await db_manager.delete_tenant_permanently(user.client_id)
    if not result:
        raise HTTPException(status_code=404, detail="Your tenant record could not be found.")
    return result


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
