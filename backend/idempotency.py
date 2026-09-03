"""
API-02 (idempotency semantics): a real, opt-in Idempotency-Key mechanism
for POST endpoints that create a new resource with no other natural
duplicate-submission guard. A client that never saw the first response
(timeout, dropped connection, proxy retry) can safely resend the SAME
request with the SAME Idempotency-Key and get back the EXACT original
response -- including a secret returned only once (see POST
/api/v1/settings/api-keys) -- instead of silently creating a second
resource.

Deliberately opt-in via the `Idempotency-Key` request header, not
automatic: a caller that never sends the header gets today's exact
behavior, unchanged -- this is additive to every endpoint it's wired
into, never a breaking change.

Scoped by (client_id, endpoint, idempotency_key) -- see db_manager.py's
idempotency_keys table. The same key from two different tenants, or
reused by one tenant across two different endpoints, are unrelated
records. If the SAME tenant reuses the SAME key on the SAME endpoint
with a DIFFERENT request body, that's a real client bug (their own retry
logic reused a key for a genuinely different request) -- rejected with a
422 rather than silently replaying the wrong cached response.

Deliberately NOT wired into every mutating endpoint in the app: only
ones where retry-without-idempotency can silently create a duplicate
resource with no other guard (see accounts.invite_teammate and
api_keys.create_api_key). POST /finance/upload-ledger, for instance,
doesn't need this -- DATA-09's delete-and-replace ingestion model and
its own identical-reupload detection already make a retried upload safe
in a different way. Same project convention as TEN-04's contained slice:
the honest, real need, not every endpoint the item's title could
technically cover.
"""
import hashlib
import json
import logging
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

try:
    from backend import db_manager
except ImportError:
    import db_manager  # type: ignore

logger = logging.getLogger("eivanta.idempotency")


def _hash_body(body: dict) -> str:
    """Canonical (sorted-key, no-whitespace) JSON hash -- two logically
    identical request bodies always hash the same regardless of key
    order, matching how a JSON client library would (re)construct the
    same payload on retry."""
    canonical = json.dumps(jsonable_encoder(body), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def replay_or_none(client_id: str, endpoint: str, request: Request, body: dict) -> Optional[JSONResponse]:
    """
    Call at the TOP of an idempotency-enabled endpoint, before any real
    work (role checks, quota checks, DB writes). Returns a JSONResponse
    to return immediately as-is -- a genuine replay of a request that
    already completed -- or None, meaning the caller should proceed with
    its real work as normal: either no Idempotency-Key header was sent
    (idempotency wasn't requested), or this is a genuinely new key that
    hasn't been seen before. Raises HTTPException(422) if the key was
    already used on this (client_id, endpoint) with a DIFFERENT body.
    """
    idem_key = request.headers.get("idempotency-key")
    if not idem_key:
        return None
    request_hash = _hash_body(body)
    try:
        cached = await db_manager.get_idempotent_response(client_id, endpoint, idem_key)
    except Exception as e:
        # A failure to CHECK idempotency must never itself block a
        # request that would otherwise succeed -- same fail-open
        # reasoning as main.py's enforce_budget_gate already applies to
        # its own gate check. Worst case: this one request re-executes
        # instead of replaying, which is a safe (if not free) outcome.
        logger.error(f"Idempotency check failed for '{endpoint}' (tenant '{client_id}'): {e}")
        return None
    if cached is None:
        return None
    if cached["request_hash"] != request_hash:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Idempotency-Key '{idem_key}' was already used on this endpoint with a different "
                f"request body. Use a new key for a genuinely different request."
            ),
        )
    return JSONResponse(status_code=cached["response_status"], content=cached["response_body"])


async def store(client_id: str, endpoint: str, request: Request, body: dict, response_status: int, response_body) -> None:
    """
    Call AFTER a real (non-replayed) request succeeds, immediately before
    returning. No-ops if no Idempotency-Key header was sent on this
    request -- a record is only ever written for a caller that opted in.
    Never call this for an error response (a 4xx/5xx) -- only a
    successful outcome should ever be replayable; an error should let a
    genuine retry try again for real, not replay the same failure
    forever.
    """
    idem_key = request.headers.get("idempotency-key")
    if not idem_key:
        return
    request_hash = _hash_body(body)
    encoded_response = jsonable_encoder(response_body)
    try:
        await db_manager.store_idempotent_response(
            client_id, endpoint, idem_key, request_hash, response_status, encoded_response
        )
    except Exception as e:
        # Same fail-open reasoning as replay_or_none above: a failure to
        # STORE the record must never fail a request whose real work
        # already succeeded. Disclosed, real limitation: if this write
        # fails, a later retry with the same key re-executes instead of
        # replaying (safe -- same outcome -- but not free, and for
        # create_api_key specifically, it would mint a genuinely second
        # key rather than returning the first one's raw secret again).
        logger.error(f"Idempotency store failed for '{endpoint}' (tenant '{client_id}'): {e}")
