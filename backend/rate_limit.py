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
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = max(1, seconds // 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


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
