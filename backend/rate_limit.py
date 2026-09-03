"""
DATA-06: per-tenant request-frequency limiting for the ledger ingestion
endpoint (POST /api/finance/upload-ledger in backend/main.py) -- the one
remaining half of this item's title after MAX_INGEST_ROWS/MAX_INGEST_COLUMNS
(byte-size and row/column caps, both already real in backend/db_manager.py)
were confirmed to already bound the SIZE of any single upload. Nothing
previously bounded the FREQUENCY of upload attempts -- a tenant (or a
compromised/malfunctioning client) could call this endpoint an unlimited
number of times per minute.

In-memory, per-process sliding window: deliberately NOT persisted to the
database or shared across multiple backend worker processes -- this is an
abuse-prevention throttle (a runaway script or loop hammering the upload
endpoint), not a security control that needs to survive a restart or be
perfectly enforced across a multi-process deployment. The right upgrade if
this backend is ever run as more than one process is a shared, external
store (Redis or similar) -- tracked as a real gap, not silently assumed
sufficient forever. Same disclosure convention as
backend/accounts.py's MAX_FAILED_LOGIN_ATTEMPTS: a reasonable starting
default, not derived from real abuse-traffic data (none exists yet).
"""
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import HTTPException

# A legitimate tenant re-uploading a corrected file a few times in quick
# succession, or scripting a handful of sequential uploads, must never be
# blocked -- this is aimed at a runaway loop or scripted abuse, not normal
# usage. Revisit once there's real usage data to tune against.
MAX_INGEST_REQUESTS_PER_WINDOW = 20
INGEST_RATE_LIMIT_WINDOW_SECONDS = 300  # 5 minutes

_lock = threading.Lock()
_attempt_times: Dict[str, Deque[float]] = defaultdict(deque)


def _format_duration(seconds: int) -> str:
    # API-03 extended this with an hours branch for its 24h daily-quota
    # window -- the original two branches (seconds/minutes), and every
    # existing caller that only ever passes a sub-hour value (DATA-06's
    # 5-minute ingestion window), are unchanged.
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    if seconds < 3600:
        minutes = max(1, seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = max(1, seconds // 3600)
    return f"{hours} hour{'s' if hours != 1 else ''}"


def check_ingestion_rate_limit(client_id: str) -> None:
    """
    Raises HTTPException(429) if `client_id` has already made
    MAX_INGEST_REQUESTS_PER_WINDOW ingestion attempts within the trailing
    INGEST_RATE_LIMIT_WINDOW_SECONDS. Call this BEFORE any real work
    (reading the upload body, touching the DB) so a client that's already
    over the limit doesn't cost this server the price of a real ingestion
    attempt at all.

    Records this attempt's timestamp as a side effect ONLY when NOT
    rate-limited -- a rejected request doesn't itself count against the
    tenant's own next window, so a client retrying immediately after a 429
    isn't punished twice for the same attempt.
    """
    now = time.monotonic()
    with _lock:
        window = _attempt_times[client_id]
        cutoff = now - INGEST_RATE_LIMIT_WINDOW_SECONDS
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= MAX_INGEST_REQUESTS_PER_WINDOW:
            retry_after = max(1, int(INGEST_RATE_LIMIT_WINDOW_SECONDS - (now - window[0])))
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Too many ledger uploads -- limit is {MAX_INGEST_REQUESTS_PER_WINDOW} per "
                    f"{INGEST_RATE_LIMIT_WINDOW_SECONDS // 60} minutes. Try again in about "
                    f"{_format_duration(retry_after)}."
                ),
            )
        window.append(now)


def reset_rate_limit_state_for_tests() -> None:
    """
    Test-only reset. This module's state is a plain in-process dict, and
    unlike backend/db_manager.py's DB_PATH (repointed to a fresh throwaway
    file per test via the isolated_db fixture) or backend.main (reloaded
    fresh per test via importlib.reload in the `app` fixture), a plain
    submodule import like `from backend import rate_limit` is NOT
    re-executed by that reload -- the same module object, and the same
    _attempt_times dict, would otherwise silently leak attempt counts
    across unrelated tests in the same pytest process. Call this at the
    start of any test that exercises rate limiting.
    """
    with _lock:
        _attempt_times.clear()


# ---------------------------------------------------------------------------
# API-03: API-wide rate limiting + tenant quotas.
#
# Enforced by ONE choke point -- main.py's enforce_api_rate_limits HTTP
# middleware, which runs for every REST request before it reaches any
# router/endpoint (same "check first, do the real work only if allowed"
# discipline as check_ingestion_rate_limit above). Three independent,
# in-memory sliding windows:
#
#  - per-tenant burst (keyed by a validly-signed JWT's client_id, decoded
#    best-effort by auth.best_effort_tenant_id_from_authorization_header):
#    generous, since one real dashboard session can fire several
#    concurrent widget calls in a burst.
#  - per-source-IP burst: applied to every request that could NOT be tied
#    to a real tenant (no/invalid/missing token) -- covers login, signup,
#    and any other unauthenticated traffic. Deliberately tighter than the
#    tenant burst: this is the highest-risk category (credential
#    stuffing, scripted signup abuse). This closes a real gap AUTH-05's
#    per-ACCOUNT lockout does not: AUTH-05 stops 5+ wrong passwords
#    against ONE email, but nothing previously stopped one source
#    hammering /auth/login with a DIFFERENT email on every attempt --
#    this per-IP bucket now does, independent of which email is tried.
#  - per-tenant daily quota: a flat abuse-prevention ceiling, independent
#    of and on top of the burst window above -- catches a tenant (or a
#    misbehaving integration) that stays under the per-minute burst limit
#    but still calls the API an unreasonable number of times over a full
#    day. Deliberately NOT billing-plan-tiered -- BILL-01..05 (paid plan
#    tiers) are explicitly out of scope for this engagement; this is a
#    single flat default for every tenant, an abuse ceiling, not a
#    monetized limit. Also the "tenant quotas" half of this item's own
#    title -- TEN-04's disclosed "no ... request quotas" gap.
#
# All three share check_ingestion_rate_limit's disclosed limitation
# above: in-memory, per-process state -- not persisted, not shared across
# multiple backend worker processes. A real multi-process/multi-instance
# deployment would need a shared external store (Redis or similar) for
# this to hold across all of them -- a real gap, not silently assumed
# sufficient. Source-IP identification also assumes request.client.host
# IS the real client IP -- true today (nothing sits in front of this
# backend), but will need reconsideration (trusting only a specific
# reverse proxy's X-Forwarded-For, never a client-supplied one) once this
# is actually deployed behind a real load balancer/reverse proxy -- see
# REL-01/CICD-04 (production deployment, out of scope for this
# engagement). And this HTTP middleware only ever runs for REST requests
# -- Starlette's @app.middleware("http") does not wrap WebSocket upgrade
# requests, so the swarm WebSocket route (backend/routers/swarm.py) is
# NOT covered by any of this -- a disclosed gap, not an oversight.
API_TENANT_BURST_LIMIT = 300
API_TENANT_BURST_WINDOW_SECONDS = 60

API_IP_BURST_LIMIT = 60
API_IP_BURST_WINDOW_SECONDS = 60

API_TENANT_DAILY_QUOTA = 20000
API_TENANT_DAILY_QUOTA_WINDOW_SECONDS = 24 * 60 * 60

_api_lock = threading.Lock()
_tenant_burst_times: Dict[str, Deque[float]] = defaultdict(deque)
_ip_burst_times: Dict[str, Deque[float]] = defaultdict(deque)
_tenant_daily_times: Dict[str, Deque[float]] = defaultdict(deque)


def _check_and_record(
    store: Dict[str, Deque[float]],
    key: str,
    limit: int,
    window_seconds: int,
    detail_prefix: str,
) -> None:
    now = time.monotonic()
    with _api_lock:
        window = store[key]
        cutoff = now - window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= limit:
            retry_after = max(1, int(window_seconds - (now - window[0])))
            raise HTTPException(
                status_code=429,
                detail=(
                    f"{detail_prefix} -- limit is {limit} per "
                    f"{_format_duration(window_seconds)}. Try again in about "
                    f"{_format_duration(retry_after)}."
                ),
                headers={"Retry-After": str(retry_after)},
            )
        window.append(now)


def check_tenant_burst_limit(client_id: str) -> None:
    """Raises HTTPException(429) if `client_id` has already made
    API_TENANT_BURST_LIMIT API requests within the trailing
    API_TENANT_BURST_WINDOW_SECONDS. Records this request's timestamp as
    a side effect only when NOT rate-limited (same non-punitive-retry
    discipline as check_ingestion_rate_limit)."""
    _check_and_record(
        _tenant_burst_times, client_id,
        API_TENANT_BURST_LIMIT, API_TENANT_BURST_WINDOW_SECONDS,
        "Too many requests for this account",
    )


def check_ip_burst_limit(source_ip: str) -> None:
    """Raises HTTPException(429) if `source_ip` (an unauthenticated
    caller) has already made API_IP_BURST_LIMIT requests within the
    trailing API_IP_BURST_WINDOW_SECONDS."""
    _check_and_record(
        _ip_burst_times, source_ip,
        API_IP_BURST_LIMIT, API_IP_BURST_WINDOW_SECONDS,
        "Too many requests from this source",
    )


def check_tenant_daily_quota(client_id: str) -> None:
    """Raises HTTPException(429) if `client_id` has already made
    API_TENANT_DAILY_QUOTA API requests within the trailing
    API_TENANT_DAILY_QUOTA_WINDOW_SECONDS (24h)."""
    _check_and_record(
        _tenant_daily_times, client_id,
        API_TENANT_DAILY_QUOTA, API_TENANT_DAILY_QUOTA_WINDOW_SECONDS,
        "Daily request quota reached for this account",
    )


def reset_all_rate_limit_state_for_tests() -> None:
    """
    Test-only reset covering EVERY in-memory rate-limit dict this module
    owns: DATA-06's ingestion-only _attempt_times above, plus API-03's
    three new dicts. Unlike the ingestion limiter (only touched by tests
    that literally call the upload endpoint), API-03's limits are
    enforced by a global HTTP middleware that every test hitting the
    `client` fixture passes through -- so this is called from an autouse
    fixture in conftest.py, not opted into per test file the way
    reset_rate_limit_state_for_tests above is.
    """
    with _lock:
        _attempt_times.clear()
    with _api_lock:
        _tenant_burst_times.clear()
        _ip_burst_times.clear()
        _tenant_daily_times.clear()
