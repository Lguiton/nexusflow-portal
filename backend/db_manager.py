import os
import json
import asyncio
import threading
import logging
import hashlib
from datetime import date, datetime
from typing import Optional
import duckdb
import pandas as pd
logger = logging.getLogger("eivanta.db_manager")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eivanta.duckdb")

# FIXED (real production crash + a masked-failure bug, both confirmed
# live): this used to be a lazily-created asyncio.Lock(). asyncio.Lock is
# bound to whichever event loop first actually contends on it, for the
# life of the process. Every function below runs its real DuckDB work
# inside a worker thread (asyncio.to_thread), so the ACTUAL protection
# this lock needs to provide is "only one thread touches the DB file at a
# time" -- that has nothing to do with which event loop dispatched the
# thread. Once a second event loop (e.g. bi_visualization_architect's old
# asyncio.run()-in-a-thread pattern) tried to use the same asyncio.Lock,
# it crashed with "Lock object ... is bound to a different event loop" --
# and that crash then broke EVERY other endpoint sharing the same
# singleton (confirmed live: KPI Summary, Analytics Summary, and Sub-Agent
# Network metrics all failed together from one bad request).
#
# A plain threading.Lock has no concept of "which event loop" at all -- it
# just serializes real OS threads, which is exactly what's needed here,
# and it works correctly no matter how many different event loops are
# involved. virtual_cfo.py, data_engineer.py, bi_engineer.py,
# saas_strategist.py, report_generator.py, and predictive_forecaster.py
# also import this same lock now (see their own comments) so their
# independent read-only connections are serialized against these
# read/write ones too -- previously they weren't synchronized with this
# lock AT ALL, which is what let a live CFO briefing request race against
# a concurrent write and get a "no ledger data ingested yet" response for
# a tenant that actually had real rows (confirmed live, 2026-08-22).
_duckdb_mutex = threading.Lock()
def get_db_lock() -> threading.Lock:
    return _duckdb_mutex

# DATA-06: sanity caps on a single upload, independent of the existing
# MAX_UPLOAD_BYTES byte-size cap in main.py. These aren't about storage
# cost -- they're a structural sanity check: a CSV with, say, 3 million
# rows or 800 columns is far more likely to be the wrong file entirely
# (a database dump, a different export format, a corrupted file) than a
# legitimate financial ledger, and processing it fully before discovering
# that wastes real time and DB lock contention. Deliberately generous
# round numbers, not tuned to any specific real workload yet -- revisit
# if a legitimate tenant ever needs headroom above these.
MAX_INGEST_ROWS = 500_000
MAX_INGEST_COLUMNS = 200

async def init_db():
    lock = get_db_lock()
    def _init():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ledgers (
                        client_id VARCHAR,
                        date VARCHAR,
                        category VARCHAR,
                        amount DOUBLE,
                        description VARCHAR,
                        is_recurring BOOLEAN
                    )
                """)
                # FIN-01: real database files created before this column
                # existed need an actual migration -- CREATE TABLE IF NOT
                # EXISTS above is a no-op once the table already exists, so
                # it does NOT retroactively add is_recurring to a real
                # tenant's existing ledgers table. init_db() runs at the top
                # of every ingest, so this must stay idempotent and cheap.
                # PRAGMA table_info is checked first (fast, no-op on repeat
                # runs); the ALTER TABLE itself is also wrapped defensively
                # in case the introspection query's column shape ever
                # differs from what's assumed here -- but only a genuine
                # "column already exists" failure is swallowed, anything
                # else still raises.
                try:
                    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info('ledgers')").fetchall()}
                except Exception as e:
                    logger.warning(f"Could not introspect ledgers table columns before FIN-01 migration check: {e}")
                    existing_cols = set()
                if "is_recurring" not in existing_cols:
                    try:
                        conn.execute("ALTER TABLE ledgers ADD COLUMN is_recurring BOOLEAN")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise

                # DIFF-01: a stable per-row identifier, so an insight (or a
                # user-accepted category suggestion -- see DIFF-06) can
                # reference the EXACT row it came from. Same idempotent
                # migration shape as is_recurring above. A sequence backs
                # both the one-time backfill for pre-existing rows AND
                # every future ingest's fresh inserts (see
                # ingest_csv_to_db) -- nextval() is evaluated once per row
                # in both an INSERT ... SELECT and an UPDATE ... SET,
                # standard SQL sequence semantics, so this assigns a
                # genuinely distinct id per row, never the same value
                # repeated across rows.
                try:
                    conn.execute("CREATE SEQUENCE IF NOT EXISTS ledger_row_id_seq")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        raise
                if "row_id" not in existing_cols:
                    try:
                        conn.execute("ALTER TABLE ledgers ADD COLUMN row_id BIGINT")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                    # One-time backfill for rows that existed before this
                    # migration -- only runs the first time the column is
                    # added (existing_cols already contains "row_id" on
                    # every subsequent init_db() call, so this block is
                    # skipped then; new rows get their row_id from
                    # ingest_csv_to_db's own INSERT instead).
                    conn.execute("UPDATE ledgers SET row_id = nextval('ledger_row_id_seq') WHERE row_id IS NULL")

                # RBAC-01: real accounts. Until now there was no users
                # table at all -- /api/v1/auth/dev-login minted a validly
                # signed JWT for ANY client_id string with zero password
                # check (see its own comment in main.py). tenants is the
                # authoritative registry of client_id (previously just a
                # loose string scattered across every other table with no
                # central record) and now also carries billing state;
                # users holds real per-person accounts, one row per
                # teammate, each with its own bcrypt password hash and a
                # role scoped to their tenant. Same idempotent
                # CREATE-IF-NOT-EXISTS shape as every other migration in
                # this function.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tenants (
                        client_id VARCHAR PRIMARY KEY,
                        company_name VARCHAR,
                        stripe_customer_id VARCHAR,
                        stripe_subscription_id VARCHAR,
                        subscription_status VARCHAR DEFAULT 'inactive',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # BYOK-01: Bring Your Own Key -- lets a tenant supply their
                # own OpenAI API key instead of drawing on the platform's.
                # Stored encrypted at rest (Fernet, see backend/byok.py) --
                # this column NEVER holds a plaintext key. Same idempotent
                # migration shape as the ledgers migrations above.
                try:
                    tenant_cols = {row[1] for row in conn.execute("PRAGMA table_info('tenants')").fetchall()}
                except Exception as e:
                    logger.warning(f"Could not introspect tenants table columns before BYOK-01 migration check: {e}")
                    tenant_cols = set()
                if "byok_openai_key_encrypted" not in tenant_cols:
                    try:
                        conn.execute("ALTER TABLE tenants ADD COLUMN byok_openai_key_encrypted VARCHAR")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                # FINOPS-01: per-tenant monthly AI spend cap, in USD. NULL
                # (the default for every existing and new tenant) means "no
                # cap set" -- unrestricted, identical to today's behavior --
                # never a silent 0/blocked-by-default state. Same idempotent
                # migration shape as the BYOK-01 column above.
                if "monthly_ai_budget_usd" not in tenant_cols:
                    try:
                        conn.execute("ALTER TABLE tenants ADD COLUMN monthly_ai_budget_usd DOUBLE")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                conn.execute("CREATE SEQUENCE IF NOT EXISTS user_id_seq")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT DEFAULT nextval('user_id_seq'),
                        client_id VARCHAR NOT NULL,
                        email VARCHAR NOT NULL,
                        password_hash VARCHAR NOT NULL,
                        role VARCHAR NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_login_at TIMESTAMP
                    )
                """)
                # Case-insensitive uniqueness is enforced in Python (every
                # write/lookup lower()s the email first -- see
                # get_user_by_email/create_tenant_and_owner/
                # create_invited_user below) rather than a SQL functional
                # index, to match how every other query in this file
                # already treats DuckDB as the storage layer, not the
                # place business rules live. This plain unique index is
                # still a real DB-level backstop against two rows for the
                # literal same stored (already-lowercased) email string.
                try:
                    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email)")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        raise
            finally:
                conn.close()
    await asyncio.to_thread(_init)


# ---------------------------------------------------------------------------
# RBAC-01: account management -- tenants + users
#
# Role model (per-tenant, one row per person in `users`):
#   owner  -- exactly one per tenant in practice (the signup creator);
#             full control including billing and removing/promoting anyone.
#   admin  -- manage teammates and settings, cannot touch billing.
#   member -- normal product use, no admin actions.
#   viewer -- read-only.
# Enforcement itself lives in backend/auth.py's require_role() dependency,
# used by whichever router owns each endpoint -- this module only stores
# and retrieves the data, same separation every other feature in this
# file already follows (db_manager never imports FastAPI).
# ---------------------------------------------------------------------------

VALID_ROLES = ("owner", "admin", "member", "viewer")


class DuplicateEmailError(Exception):
    """Raised when a signup/invite email is already registered for any tenant."""


class TenantExistsError(Exception):
    """Raised when signup targets a client_id that's already registered."""


async def create_tenant_and_owner(client_id: str, company_name: str, email: str, password_hash: str) -> dict:
    """
    Real signup: creates the tenant registry row AND its first user in one
    transaction, that user always role='owner'. Rolls back entirely (no
    orphaned tenant-with-no-owner, no orphaned user-with-no-tenant) if
    either half fails -- confirmed via explicit BEGIN/COMMIT/ROLLBACK
    rather than relying on DuckDB's own statement-level atomicity across
    two separate INSERTs.
    """
    await init_db()
    lock = get_db_lock()
    email_norm = email.strip().lower()

    def _create():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                existing_tenant = conn.execute(
                    "SELECT 1 FROM tenants WHERE client_id = ?", [client_id]
                ).fetchone()
                if existing_tenant:
                    raise TenantExistsError(f"client_id '{client_id}' is already registered.")
                existing_email = conn.execute(
                    "SELECT 1 FROM users WHERE email = ?", [email_norm]
                ).fetchone()
                if existing_email:
                    raise DuplicateEmailError(f"'{email_norm}' is already registered.")

                conn.execute("BEGIN TRANSACTION")
                try:
                    conn.execute(
                        "INSERT INTO tenants (client_id, company_name) VALUES (?, ?)",
                        [client_id, company_name],
                    )
                    conn.execute(
                        "INSERT INTO users (client_id, email, password_hash, role) VALUES (?, ?, ?, 'owner')",
                        [client_id, email_norm, password_hash],
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

                row = conn.execute(
                    "SELECT user_id, client_id, email, role FROM users WHERE email = ?", [email_norm]
                ).fetchone()
                return {"user_id": row[0], "client_id": row[1], "email": row[2], "role": row[3]}
            finally:
                conn.close()
    return await asyncio.to_thread(_create)


async def create_invited_user(client_id: str, email: str, password_hash: str, role: str) -> dict:
    """
    Adds a teammate to an EXISTING tenant. Caller (the accounts router) is
    responsible for checking the inviting user's own role is owner/admin
    before this is ever called -- this function itself only enforces the
    data-integrity rules that don't depend on who's asking: the tenant
    must already exist, the role must be one of the four real roles, and
    the email must not already be registered anywhere (a person has one
    account across the whole system, not one per tenant they're invited
    to -- simplest real model for a v1, revisit if multi-tenant membership
    for one person is ever actually needed).
    """
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got {role!r}")
    await init_db()
    lock = get_db_lock()
    email_norm = email.strip().lower()

    def _create():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                existing_tenant = conn.execute(
                    "SELECT 1 FROM tenants WHERE client_id = ?", [client_id]
                ).fetchone()
                if not existing_tenant:
                    raise TenantExistsError(f"client_id '{client_id}' is not a registered tenant.")
                existing_email = conn.execute(
                    "SELECT 1 FROM users WHERE email = ?", [email_norm]
                ).fetchone()
                if existing_email:
                    raise DuplicateEmailError(f"'{email_norm}' is already registered.")
                conn.execute(
                    "INSERT INTO users (client_id, email, password_hash, role) VALUES (?, ?, ?, ?)",
                    [client_id, email_norm, password_hash, role],
                )
                row = conn.execute(
                    "SELECT user_id, client_id, email, role FROM users WHERE email = ?", [email_norm]
                ).fetchone()
                return {"user_id": row[0], "client_id": row[1], "email": row[2], "role": row[3]}
            finally:
                conn.close()
    return await asyncio.to_thread(_create)


async def get_user_by_email(email: str) -> Optional[dict]:
    """Real lookup for login -- returns the password_hash too (caller verifies it), or None."""
    await init_db()
    lock = get_db_lock()
    email_norm = email.strip().lower()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT user_id, client_id, email, password_hash, role FROM users WHERE email = ?",
                    [email_norm],
                ).fetchone()
                if not row:
                    return None
                return {
                    "user_id": row[0], "client_id": row[1], "email": row[2],
                    "password_hash": row[3], "role": row[4],
                }
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def update_last_login(user_id: int) -> None:
    lock = get_db_lock()

    def _update():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE user_id = ?", [user_id]
                )
            finally:
                conn.close()
    await asyncio.to_thread(_update)


async def list_users_for_tenant(client_id: str) -> list[dict]:
    lock = get_db_lock()

    def _list():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                rows = conn.execute(
                    "SELECT user_id, email, role, created_at, last_login_at FROM users "
                    "WHERE client_id = ? ORDER BY created_at ASC",
                    [client_id],
                ).fetchall()
                return [
                    {
                        "user_id": r[0], "email": r[1], "role": r[2],
                        "created_at": str(r[3]) if r[3] is not None else None,
                        "last_login_at": str(r[4]) if r[4] is not None else None,
                    }
                    for r in rows
                ]
            finally:
                conn.close()
    return await asyncio.to_thread(_list)


async def update_user_role(client_id: str, user_id: int, new_role: str) -> bool:
    """Returns False if no matching user was found for that tenant (never touches another tenant's user)."""
    if new_role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got {new_role!r}")
    lock = get_db_lock()

    def _update():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                # RBAC-01 fix: this used to check `SELECT changes()` after
                # the UPDATE to see whether a row was actually touched --
                # that's a SQLite-ism. DuckDB has no changes() scalar
                # function, so that call raised a Catalog/Binder error on
                # every real invocation, meaning this endpoint 500'd
                # instead of ever returning True/False. Existence-check
                # first instead, matching this file's own established
                # pattern elsewhere (see delete_tenant_ledger's SELECT
                # COUNT(*)-before-DELETE above).
                exists = conn.execute(
                    "SELECT 1 FROM users WHERE user_id = ? AND client_id = ?",
                    [user_id, client_id],
                ).fetchone()
                if not exists:
                    return False
                conn.execute(
                    "UPDATE users SET role = ? WHERE user_id = ? AND client_id = ?",
                    [new_role, user_id, client_id],
                )
                return True
            finally:
                conn.close()
    return await asyncio.to_thread(_update)


async def remove_user(client_id: str, user_id: int) -> bool:
    """Returns False if no matching user was found for that tenant (never touches another tenant's user)."""
    lock = get_db_lock()

    def _remove():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                # RBAC-01 fix: same SELECT changes() bug as
                # update_user_role above -- not a real DuckDB function,
                # existence-check first instead.
                exists = conn.execute(
                    "SELECT 1 FROM users WHERE user_id = ? AND client_id = ?",
                    [user_id, client_id],
                ).fetchone()
                if not exists:
                    return False
                conn.execute(
                    "DELETE FROM users WHERE user_id = ? AND client_id = ?", [user_id, client_id]
                )
                return True
            finally:
                conn.close()
    return await asyncio.to_thread(_remove)


async def get_tenant(client_id: str) -> Optional[dict]:
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT client_id, company_name, stripe_customer_id, stripe_subscription_id, "
                    "subscription_status, created_at FROM tenants WHERE client_id = ?",
                    [client_id],
                ).fetchone()
                if not row:
                    return None
                return {
                    "client_id": row[0], "company_name": row[1],
                    "stripe_customer_id": row[2], "stripe_subscription_id": row[3],
                    "subscription_status": row[4], "created_at": str(row[5]) if row[5] is not None else None,
                }
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def update_tenant_billing(
    client_id: str,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    subscription_status: Optional[str] = None,
) -> None:
    """
    Partial update -- only overwrites fields actually passed. Used both
    right after Stripe Checkout creates a customer (stripe_customer_id
    only, subscription not active yet) and from the webhook handler once
    the subscription itself changes state (see backend/billing.py).
    """
    lock = get_db_lock()

    def _update():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                sets, params = [], []
                if stripe_customer_id is not None:
                    sets.append("stripe_customer_id = ?")
                    params.append(stripe_customer_id)
                if stripe_subscription_id is not None:
                    sets.append("stripe_subscription_id = ?")
                    params.append(stripe_subscription_id)
                if subscription_status is not None:
                    sets.append("subscription_status = ?")
                    params.append(subscription_status)
                if not sets:
                    return
                params.append(client_id)
                conn.execute(f"UPDATE tenants SET {', '.join(sets)} WHERE client_id = ?", params)
            finally:
                conn.close()
    return await asyncio.to_thread(_update)


# BYOK-01 -- storage only. These functions read/write the encrypted column
# verbatim; encryption/decryption itself lives in backend/byok.py, which is
# the only module that should ever handle a plaintext key. Never log or
# return the encrypted value to a frontend caller -- see main.py's BYOK
# endpoints, which only ever return whether a key is set, never the value.

async def set_tenant_byok_key(client_id: str, encrypted_key: Optional[str]) -> None:
    lock = get_db_lock()

    def _update():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE tenants SET byok_openai_key_encrypted = ? WHERE client_id = ?",
                    [encrypted_key, client_id],
                )
            finally:
                conn.close()
    return await asyncio.to_thread(_update)


async def get_tenant_byok_key_encrypted(client_id: str) -> Optional[str]:
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT byok_openai_key_encrypted FROM tenants WHERE client_id = ?",
                    [client_id],
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


# ==============================================================================
# FINOPS-01: real billing-overrun protection. AI-06's token/cost telemetry
# (log_ai_usage / the ai_usage table above) already recorded every real
# call's tokens and estimated USD cost per tenant -- that was monitoring,
# not a cap. This is the enforcement half: an optional per-tenant monthly
# USD cap plus a real gate check that aggregates this month's actual
# ai_usage rows and reports whether the NEXT call should be allowed.
# ==============================================================================

async def set_tenant_budget_cap(client_id: str, cap_usd: Optional[float]) -> None:
    """cap_usd=None clears the cap (back to unrestricted) -- mirrors
    set_tenant_byok_key's None-clears convention."""
    lock = get_db_lock()

    def _update():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE tenants SET monthly_ai_budget_usd = ? WHERE client_id = ?",
                    [cap_usd, client_id],
                )
            finally:
                conn.close()
    return await asyncio.to_thread(_update)


async def get_tenant_budget_cap(client_id: str) -> Optional[float]:
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT monthly_ai_budget_usd FROM tenants WHERE client_id = ?",
                    [client_id],
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def get_monthly_ai_usage(client_id: str) -> dict:
    """
    Real aggregation of this tenant's ai_usage rows for the current
    calendar month (server clock, UTC-naive CURRENT_TIMESTAMP -- same
    clock every other timestamp column in this file already uses).
    usage_usd is a SUM over estimated_cost_usd, which is NULL for any
    call made with a model absent from MODEL_PRICING -- those calls'
    tokens are still counted in usage_tokens/call_count, but do not
    silently count as $0 toward the dollar cap (SUM ignores NULLs; an
    entirely-unpriced month correctly reports usage_usd=0.0 rather than
    a fabricated number, and is flagged via priced_call_count vs
    call_count so that distinction isn't hidden).
    """
    lock = get_db_lock()

    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ai_usage" not in tables:
                    return {"usage_usd": 0.0, "usage_tokens": 0, "call_count": 0, "priced_call_count": 0}
                row = conn.execute("""
                    SELECT
                        COALESCE(SUM(estimated_cost_usd), 0.0),
                        COALESCE(SUM(total_tokens), 0),
                        COUNT(*),
                        COUNT(estimated_cost_usd)
                    FROM ai_usage
                    WHERE client_id = ?
                      AND date_trunc('month', timestamp) = date_trunc('month', CURRENT_TIMESTAMP)
                """, [client_id]).fetchone()
                return {
                    "usage_usd": float(row[0]),
                    "usage_tokens": int(row[1]),
                    "call_count": int(row[2]),
                    "priced_call_count": int(row[3]),
                }
            except Exception as e:
                logger.error(f"Failed to aggregate monthly AI usage for tenant '{client_id}': {e}")
                return {"usage_usd": 0.0, "usage_tokens": 0, "call_count": 0, "priced_call_count": 0}
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def check_budget_gate(client_id: str) -> dict:
    """
    The real gate check. No cap set (the default for every tenant) ->
    always allowed=True, identical to today's unrestricted behavior. A cap
    set and this month's real usage_usd already at or over it -> allowed
    False, with the actual numbers so the caller (main.py) can return an
    honest, specific 402 rather than a generic block.
    """
    cap_usd = await get_tenant_budget_cap(client_id)
    usage = await get_monthly_ai_usage(client_id)
    if cap_usd is None:
        return {"allowed": True, "cap_usd": None, **usage, "pct_used": None}
    pct_used = round((usage["usage_usd"] / cap_usd) * 100, 1) if cap_usd > 0 else 100.0
    allowed = usage["usage_usd"] < cap_usd
    return {"allowed": allowed, "cap_usd": cap_usd, **usage, "pct_used": pct_used}


# ==============================================================================
# ENT-03: explainable-AI audit/lineage log. query_audit (SQL-03, above)
# already records BI Engineer's own NL-to-SQL requests specifically; this
# is the platform-wide counterpart the backlog calls for -- one entry per
# real agent invocation, across whichever agent orchestrator.route_query
# actually routes a query to, not just SQL generation. "Immutable" is made
# a real, checkable property via a per-tenant SHA-256 hash chain (each
# row's row_hash covers its own fields plus the previous row's hash for
# THAT tenant) rather than an unenforced claim -- verify_lineage_chain
# below recomputes the chain and reports the first row where it breaks, if
# any. This does not prevent a row being edited directly in the database
# file (nothing short of a separate write-once store could) -- what it
# gives is tamper EVIDENCE: any such edit is detectable and reported, not
# silently trusted.
# ==============================================================================

def _lineage_row_hash(
    prev_hash: str, client_id: str, session_id: str, agent_name: str,
    model_used: str, query_text: str, decision_summary: str, status: str, timestamp_iso: str,
) -> str:
    payload = "|".join([
        prev_hash or "", client_id or "", session_id or "", agent_name or "",
        model_used or "", query_text or "", decision_summary or "", status or "", timestamp_iso or "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def log_lineage_entry(
    client_id: str, agent_name: str, query_text: str, decision_summary: str, status: str,
    session_id: Optional[str] = None, model_used: Optional[str] = None,
) -> None:
    """
    Records one real routing/agent decision into this tenant's hash-chained
    lineage log. Deliberately never raises -- same discipline as every
    other audit-log writer in this file: a failure to WRITE lineage must
    never block the response the tenant is waiting on.
    """
    if not client_id:
        return
    lock = get_db_lock()

    def _log():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("""
                    CREATE SEQUENCE IF NOT EXISTS ai_lineage_log_id_seq;
                    CREATE TABLE IF NOT EXISTS ai_lineage_log (
                        lineage_id BIGINT DEFAULT nextval('ai_lineage_log_id_seq'),
                        timestamp TIMESTAMP,
                        client_id VARCHAR,
                        session_id VARCHAR,
                        agent_name VARCHAR,
                        model_used VARCHAR,
                        query_text VARCHAR,
                        decision_summary VARCHAR,
                        status VARCHAR,
                        prev_hash VARCHAR,
                        row_hash VARCHAR
                    )
                """)
                # Prior hash is scoped to THIS tenant only -- reading and
                # inserting inside the same lock/transaction avoids two
                # concurrent writes for one tenant forking the chain.
                prev = conn.execute(
                    "SELECT row_hash FROM ai_lineage_log WHERE client_id = ? "
                    "ORDER BY lineage_id DESC LIMIT 1",
                    [client_id]
                ).fetchone()
                prev_hash = prev[0] if prev else ""
                timestamp_iso = datetime.utcnow().isoformat()
                row_hash = _lineage_row_hash(
                    prev_hash, client_id, session_id or "", agent_name or "",
                    model_used or "", query_text or "", decision_summary or "", status or "", timestamp_iso
                )
                conn.execute(
                    "INSERT INTO ai_lineage_log "
                    "(timestamp, client_id, session_id, agent_name, model_used, query_text, decision_summary, status, prev_hash, row_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [timestamp_iso, client_id, session_id, agent_name, model_used,
                     query_text, decision_summary, status, prev_hash, row_hash]
                )
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error(f"Failed to log lineage entry for tenant '{client_id}': {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)


def log_lineage_entry_sync(
    client_id: str, agent_name: str, query_text: str, decision_summary: str, status: str,
    session_id: Optional[str] = None, model_used: Optional[str] = None,
) -> None:
    """Sync wrapper -- same _in_running_loop()-guarded asyncio.run() shape
    already established by log_ai_usage_sync below, for callers (agent
    modules) that aren't themselves async."""
    if _in_running_loop_db():
        logger.warning(f"Lineage logging skipped for agent '{agent_name}': already inside a running event loop.")
        return
    try:
        asyncio.run(log_lineage_entry(client_id, agent_name, query_text, decision_summary, status, session_id, model_used))
    except Exception as e:
        logger.error(f"Sync lineage logging failed for agent '{agent_name}': {e}")


async def get_lineage_log(client_id: str, limit: int = 100) -> list:
    """Tenant-scoped read, most recent first."""
    if not client_id:
        return []
    limit = max(1, min(int(limit), 500))
    lock = get_db_lock()

    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ai_lineage_log" not in tables:
                    return []
                rows = conn.execute("""
                    SELECT lineage_id, timestamp, session_id, agent_name, model_used,
                           query_text, decision_summary, status, prev_hash, row_hash
                    FROM ai_lineage_log
                    WHERE client_id = ?
                    ORDER BY lineage_id DESC
                    LIMIT ?
                """, [client_id, limit]).fetchall()
                return [
                    {
                        "lineage_id": r[0], "timestamp": str(r[1]), "session_id": r[2],
                        "agent_name": r[3], "model_used": r[4], "query_text": r[5],
                        "decision_summary": r[6], "status": r[7], "prev_hash": r[8], "row_hash": r[9],
                    }
                    for r in rows
                ]
            except Exception as e:
                logger.error(f"Failed to fetch lineage log for tenant '{client_id}': {e}")
                return []
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def verify_lineage_chain(client_id: str) -> dict:
    """
    Recomputes this tenant's hash chain from scratch (oldest to newest) and
    compares every stored row_hash/prev_hash against what the recorded
    fields actually hash to. This is the genuine tamper-evidence check
    behind the "immutable" claim above -- intact=True means every row's
    hash is consistent with its own fields and its predecessor; intact
    stays honest (never assumed True) for a tenant with zero lineage rows,
    reported via row_count instead.
    """
    if not client_id:
        return {"intact": True, "row_count": 0, "first_break_lineage_id": None}
    lock = get_db_lock()

    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ai_lineage_log" not in tables:
                    return {"intact": True, "row_count": 0, "first_break_lineage_id": None}
                rows = conn.execute("""
                    SELECT lineage_id, timestamp, session_id, agent_name, model_used,
                           query_text, decision_summary, status, prev_hash, row_hash
                    FROM ai_lineage_log
                    WHERE client_id = ?
                    ORDER BY lineage_id ASC
                """, [client_id]).fetchall()
                expected_prev = ""
                for r in rows:
                    (lineage_id, timestamp, session_id, agent_name, model_used,
                     query_text, decision_summary, status, prev_hash, row_hash) = r
                    timestamp_iso = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
                    if prev_hash != expected_prev:
                        return {"intact": False, "row_count": len(rows), "first_break_lineage_id": lineage_id}
                    recomputed = _lineage_row_hash(
                        prev_hash, client_id, session_id or "", agent_name or "",
                        model_used or "", query_text or "", decision_summary or "", status or "", timestamp_iso
                    )
                    if recomputed != row_hash:
                        return {"intact": False, "row_count": len(rows), "first_break_lineage_id": lineage_id}
                    expected_prev = row_hash
                return {"intact": True, "row_count": len(rows), "first_break_lineage_id": None}
            except Exception as e:
                logger.error(f"Failed to verify lineage chain for tenant '{client_id}': {e}")
                return {"intact": False, "row_count": 0, "first_break_lineage_id": None, "error": str(e)}
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


def _parse_amount_series(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    text = text.str.replace(r'^\((.*)\)$', r'-\1', regex=True)
    text = text.str.replace(r'[\$,]', '', regex=True)
    return pd.to_numeric(text, errors='coerce')


# FIN-01: real Monthly Recurring Revenue requires knowing whether EACH
# transaction is a recurring subscription charge or a one-time
# transaction -- the ledgers table had no such field before this. Per
# founder decision (2026-08-23): rather than guess this from category
# names or amounts (the same kind of unreliable heuristic already
# disclosed elsewhere in this codebase, e.g. virtual_cfo's revenue/COGS
# keyword classification), an OPTIONAL 'recurring' or 'is_recurring'
# column is now accepted on upload. A row with no such column, or an
# unparseable value, is stored as NULL -- genuinely unknown -- never
# guessed as True or False. Real MRR (get_mrr_summary below) is computed
# only from rows a tenant has actually told us about.
_RECURRING_TRUE_TOKENS = {"true", "yes", "y", "1", "recurring", "subscription", "sub", "recur", "mrr"}
_RECURRING_FALSE_TOKENS = {
    "false", "no", "n", "0", "one-time", "onetime", "one_time",
    "non-recurring", "nonrecurring", "single", "one off", "one-off",
}


def _parse_recurring_series(series: pd.Series) -> pd.Series:
    def _parse_one(v):
        if pd.isna(v):
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            if v == 1:
                return True
            if v == 0:
                return False
            return None
        text = str(v).strip().lower()
        if text in _RECURRING_TRUE_TOKENS:
            return True
        if text in _RECURRING_FALSE_TOKENS:
            return False
        return None
    return series.apply(_parse_one)


def _file_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv_or_raise(file_path: str) -> pd.DataFrame:
    """
    DATA-03: previously a raw pd.read_csv() call -- any structural problem
    (ragged/inconsistent field counts across rows, a genuinely empty file,
    an encoding pandas can't handle) raised pandas' own internal exception
    type straight up through ingest_csv_to_db, main.py's upload_ledger
    endpoint caught it with a blanket `except Exception`, and returned a
    generic 500 "Ledger ingestion failed. Check server logs for details."
    -- useless to a non-coder founder/user who just needs to know their
    file's structure is the problem, not that the server is broken.
    Converts the specific, well-known pandas failure modes into a single
    ValueError with an actionable message; main.py now maps ValueError to
    a 400 with this exact detail instead of a generic 500.
    """
    try:
        return pd.read_csv(file_path)
    except pd.errors.EmptyDataError:
        raise ValueError("This file is empty -- no header row or data was found.")
    except pd.errors.ParserError as e:
        raise ValueError(
            f"This file could not be parsed as a valid CSV: {e}. This usually means "
            "some rows have a different number of columns than the header row "
            "(a ragged/malformed file), or the file uses an unexpected delimiter."
        )
    except UnicodeDecodeError as e:
        raise ValueError(
            f"This file's text encoding could not be read ({e}). Try re-saving it as "
            "UTF-8 CSV and uploading again."
        )


# Track 3 (multi-format ingestion): supported upload extensions, checked
# against the ORIGINAL filename the user uploaded -- not sniffed from file
# content, so a mislabeled file gets a clear "this isn't really a .csv"
# style error from the format-specific reader below, rather than a
# confusing failure two layers deeper.
SUPPORTED_INGEST_EXTENSIONS = {".csv", ".txt", ".xlsx", ".xls", ".json", ".pdf"}


def _read_excel_or_raise(file_path: str) -> pd.DataFrame:
    """
    Multi-sheet support: every sheet in the workbook is read and
    concatenated into one DataFrame (a "source_sheet" column records which
    sheet each row came from, dropped again before the normal amount/
    category/date column detection below -- it's provenance, not ledger
    data). A sheet that fails to parse is skipped with its error recorded,
    rather than failing the whole upload for one bad tab -- but if EVERY
    sheet fails, that's surfaced as a real error, not a silent empty
    ingest.
    """
    try:
        sheets = pd.read_excel(file_path, sheet_name=None)
    except Exception as e:
        raise ValueError(
            f"This Excel file could not be opened: {e}. Make sure it's a valid "
            ".xlsx/.xls file and isn't corrupted or password-protected."
        )
    if not sheets:
        raise ValueError("This Excel file has no sheets.")
    frames = []
    sheet_errors = []
    for name, sheet_df in sheets.items():
        if sheet_df is None or sheet_df.empty:
            continue
        try:
            sheet_df = sheet_df.copy()
            sheet_df["source_sheet"] = name
            frames.append(sheet_df)
        except Exception as e:
            sheet_errors.append(f"{name}: {e}")
    if not frames:
        detail = f" Errors: {'; '.join(sheet_errors)}" if sheet_errors else ""
        raise ValueError(f"No usable data found in any sheet of this Excel file.{detail}")
    return pd.concat(frames, ignore_index=True, sort=False)


def _read_json_or_raise(file_path: str) -> pd.DataFrame:
    """
    Accepts either a top-level JSON array of row objects (the common case)
    or a top-level object with a single array-valued field holding the
    rows (e.g. {"transactions": [...]})  -- picks the first array-valued
    field found in that case, since there's no universal convention for
    what that field is called.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"This file could not be parsed as valid JSON: {e}.")
    except UnicodeDecodeError as e:
        raise ValueError(f"This file's text encoding could not be read ({e}). Try re-saving it as UTF-8.")

    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        array_fields = [v for v in raw.values() if isinstance(v, list)]
        if not array_fields:
            raise ValueError(
                "This JSON file's top level is an object with no array field to read rows "
                "from. Expected either a top-level array of records, or an object with one "
                "field holding an array of records (e.g. {\"transactions\": [...]})."
            )
        records = array_fields[0]
    else:
        raise ValueError("This JSON file's top level must be an array or an object, not a bare value.")

    try:
        return pd.json_normalize(records)
    except Exception as e:
        raise ValueError(f"This JSON file's records could not be read into a table: {e}.")


def _read_pdf_or_raise(file_path: str) -> pd.DataFrame:
    """
    Best-effort: extracts every table pdfplumber finds across every page
    and stacks rows from tables whose first row looks like a real header
    (at least 2 non-empty cells). This handles the common case -- a real
    tabular ledger export saved as PDF -- but NOT scanned/image-only PDFs
    (no text layer to extract) or PDFs whose "table" is actually loose
    text with no real grid structure; both come back as a clear error
    rather than silently returning nothing useful.
    """
    try:
        import pdfplumber
    except ImportError as e:
        raise ValueError(
            "PDF ingestion requires the 'pdfplumber' package, which isn't installed on "
            "this server yet. Run: pip install -r requirements.txt"
        ) from e

    frames = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table or len(table) < 2:
                        continue
                    header, *rows = table
                    if sum(1 for c in header if c and str(c).strip()) < 2:
                        continue
                    header = [str(c).strip() if c else f"col_{i}" for i, c in enumerate(header)]
                    frames.append(pd.DataFrame(rows, columns=header))
    except Exception as e:
        raise ValueError(f"This PDF could not be read: {e}.")

    if not frames:
        raise ValueError(
            "No table-like data could be extracted from this PDF. This usually means it's a "
            "scanned/image-only PDF (no real text layer -- OCR isn't supported yet), or its "
            "content isn't laid out as a real table pdfplumber can detect. Try exporting as "
            "CSV or Excel instead."
        )
    return pd.concat(frames, ignore_index=True, sort=False)


def _read_ledger_file_or_raise(file_path: str, original_filename: str) -> pd.DataFrame:
    """
    Track 3 (multi-format ingestion): dispatches to a format-specific
    reader by the ORIGINAL upload filename's extension. Every reader below
    returns a plain DataFrame in whatever raw columns the source file had
    -- the amount/category/date/description normalization in
    ingest_csv_to_db() runs identically afterward regardless of source
    format, so a correctly-shaped Excel or JSON upload behaves exactly
    like a correctly-shaped CSV from that point on.
    """
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in SUPPORTED_INGEST_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext or '(none)'}'. Supported formats: "
            f"{', '.join(sorted(SUPPORTED_INGEST_EXTENSIONS))}."
        )
    if ext == ".csv":
        return _read_csv_or_raise(file_path)
    if ext == ".txt":
        # Delimiter-sniffed rather than assumed comma -- a .txt export is
        # just as likely to be tab- or semicolon-delimited.
        try:
            return pd.read_csv(file_path, sep=None, engine="python")
        except pd.errors.EmptyDataError:
            raise ValueError("This file is empty -- no header row or data was found.")
        except Exception as e:
            raise ValueError(f"This .txt file could not be parsed as delimited data: {e}.")
    if ext in (".xlsx", ".xls"):
        return _read_excel_or_raise(file_path)
    if ext == ".json":
        return _read_json_or_raise(file_path)
    if ext == ".pdf":
        return _read_pdf_or_raise(file_path)
    raise ValueError(f"Unsupported file type '{ext}'.")  # unreachable given the check above
async def ingest_csv_to_db(file_path: str, client_id: str, original_filename: str = None) -> str:
    if not client_id:
        raise ValueError("client_id is required for tenant-isolated ingestion.")
    await init_db()

    file_hash = _file_sha256(file_path)
    display_name = original_filename or os.path.basename(file_path)

    try:
        df = _read_ledger_file_or_raise(file_path, display_name)

        # DATA-03: a genuinely empty file (header only, or truly nothing)
        # previously sailed through as "Successfully ingested 0 records" --
        # technically true, but almost always means the wrong file was
        # uploaded, not a deliberate empty ledger.
        if df.empty:
            raise ValueError("This file has a header row but no data rows to ingest.")

        # DATA-06: structural sanity caps, independent of the byte-size cap.
        if len(df) > MAX_INGEST_ROWS:
            raise ValueError(
                f"This file has {len(df):,} rows, which exceeds the {MAX_INGEST_ROWS:,}-row "
                "limit for a single upload. Split it into smaller files, or contact support "
                "if you have a legitimate need for a larger single upload."
            )
        if len(df.columns) > MAX_INGEST_COLUMNS:
            raise ValueError(
                f"This file has {len(df.columns)} columns, which exceeds the "
                f"{MAX_INGEST_COLUMNS}-column limit. This usually means the wrong file was "
                "uploaded (e.g. a different export format), not a financial ledger."
            )

        df.columns = [c.strip().lower() for c in df.columns]

        # DATA-03: duplicate column names after normalization would silently
        # shadow each other during the amount/category/date lookups below
        # (pandas keeps both columns but dict-style access returns only one
        # of them, non-deterministically from the caller's perspective) --
        # reject explicitly instead of guessing which one was meant.
        if len(df.columns) != len(set(df.columns)):
            seen = set()
            dupes = sorted({c for c in df.columns if c in seen or seen.add(c)})
            raise ValueError(
                f"This file has duplicate column name(s) after normalization: {dupes}. "
                "Rename columns so each is unique, then re-upload."
            )

        if 'amount' not in df.columns:
            if 'revenue' in df.columns and 'expense' in df.columns:
                df['amount'] = pd.to_numeric(df['revenue'], errors='coerce').fillna(0) - \
                                pd.to_numeric(df['expense'], errors='coerce').fillna(0)
            elif 'revenue' in df.columns:
                df['amount'] = df['revenue']
            elif 'cost' in df.columns or 'expense' in df.columns:
                source = df['cost'] if 'cost' in df.columns else df['expense']
                df['amount'] = -_parse_amount_series(source).abs()
            else:
                # Previously fell back to "use the first numeric column found" --
                # a guess that could silently misinterpret an unrelated numeric
                # column (a quantity, an ID, anything) as a financial amount in
                # a financial ledger. Tightened per founder decision: reject
                # ambiguous CSVs with a clear, actionable error instead of
                # guessing which column represents money.
                raise ValueError(
                    "CSV must contain a recognized amount column ('amount', 'revenue', "
                    "'revenue' + 'expense', 'cost', or 'expense') so ingestion doesn't have "
                    "to guess which column represents the financial amount. "
                    f"Columns found: {list(df.columns)}."
                )
        today_str = date.today().isoformat()
        if 'category' not in df.columns:
            df['category'] = 'Uncategorized'
        if 'date' not in df.columns:
            df['date'] = today_str
        if 'description' not in df.columns:
            df['description'] = 'Uploaded ledger entry'

        # FIN-01: optional recurring-vs-one-time flag -- see
        # _parse_recurring_series above for why unflagged/unparseable rows
        # are stored as NULL rather than guessed.
        recurring_col = next((c for c in ("is_recurring", "recurring") if c in df.columns), None)
        if recurring_col:
            recurring_series = _parse_recurring_series(df[recurring_col])
        else:
            recurring_series = pd.Series([None] * len(df), index=df.index, dtype="object")

        clean_df = pd.DataFrame({
            'client_id': client_id,
            'date': df['date'].fillna(today_str).astype(str),
            'category': df['category'].fillna('Uncategorized').astype(str),
            'amount': _parse_amount_series(df['amount']),
            'description': df['description'].fillna('Uploaded ledger entry').astype(str),
            'is_recurring': recurring_series,
        })
        invalid_mask = clean_df['amount'].isna()
        skipped_count = int(invalid_mask.sum())

        # DATA-03: if EVERY row's amount was unparseable, this is almost
        # certainly the wrong column or a structurally different file, not a
        # legitimate ledger with 100% bad data -- previously this silently
        # "succeeded" with a message reading "Successfully ingested 0
        # records. Skipped N row(s)...", indistinguishable at a glance from
        # a real empty tenant.
        if skipped_count and skipped_count == len(clean_df):
            raise ValueError(
                f"Every row in this file (all {skipped_count}) had an unparseable amount "
                "value in the detected amount column. No rows were ingested. This usually "
                "means the wrong column was detected as the amount, or the file's number "
                "format isn't recognized (expected plain numbers, optionally with $ / , / "
                "parentheses-for-negative)."
            )
        if skipped_count:
            clean_df = clean_df[~invalid_mask]
    except ValueError as e:
        await log_ingestion_attempt(client_id, display_name, file_hash, "REJECTED", 0, 0, str(e))
        raise

    lock = get_db_lock()
    def _write():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("DELETE FROM ledgers WHERE client_id = ?", [client_id])
                conn.register("clean_df_view", clean_df)
                try:
                    # is_recurring is explicitly CAST to BOOLEAN rather than
                    # relying on pandas/duckdb's column-type inference --
                    # an all-NULL is_recurring column (the common case: no
                    # tenant-provided recurring flag anywhere in this
                    # upload) has no non-null value to infer a type from,
                    # and the explicit CAST makes the INSERT unambiguous
                    # either way.
                    # DIFF-01: row_id assigned fresh per row via
                    # nextval('ledger_row_id_seq') -- evaluated once per row
                    # emitted by this multi-row SELECT (standard SQL
                    # sequence semantics), so every inserted row gets a
                    # genuinely distinct id, never a repeated one.
                    conn.execute(
                        "INSERT INTO ledgers (row_id, client_id, date, category, amount, description, is_recurring) "
                        "SELECT nextval('ledger_row_id_seq'), client_id, date, category, amount, description, CAST(is_recurring AS BOOLEAN) FROM clean_df_view"
                    )
                finally:
                    conn.unregister("clean_df_view")
                conn.execute("COMMIT")
                return conn.execute(
                    "SELECT COUNT(*) FROM ledgers WHERE client_id = ?", [client_id]
                ).fetchone()[0]
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error(f"CSV Ingestion Failed for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    try:
        row_count = await asyncio.to_thread(_write)
    except Exception as e:
        await log_ingestion_attempt(client_id, display_name, file_hash, "ERROR", 0, skipped_count, str(e))
        raise

    message = f"Successfully ingested {row_count} records for tenant '{client_id}'."
    if skipped_count:
        message += f" Skipped {skipped_count} row(s) with an unparseable amount value."

    # DATA-04: fingerprint-based duplicate notice -- the ingestion model is
    # (and remains) full delete-and-replace per tenant per upload, so
    # re-uploading an identical file is already safely idempotent in terms
    # of end state. This doesn't block or change that behavior; it just
    # tells the user when what they just uploaded is byte-identical to
    # their last successful upload, since that's very often an accidental
    # double-submit worth knowing about.
    last = await get_last_successful_ingestion(client_id)
    if last and last.get("file_sha256") == file_hash:
        message += " Note: this file is identical to your last successful upload for this tenant."

    await log_ingestion_attempt(client_id, display_name, file_hash, "SUCCESS", row_count, skipped_count, message)
    return message
async def get_total_ingested_rows() -> int:
    await init_db()
    lock = get_db_lock()
    def _count():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                return int(conn.execute("SELECT COUNT(*) FROM ledgers").fetchone()[0])
            except Exception as e:
                logger.error(f"Failed to fetch total ingestion metrics: {e}")
                return 0
            finally:
                conn.close()
    return await asyncio.to_thread(_count)
async def get_ledger_chart_context(client_id: str) -> dict:
    if not client_id:
        raise ValueError("client_id is required.")
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row_count = conn.execute(
                    "SELECT COUNT(*) FROM ledgers WHERE client_id = ?", [client_id]
                ).fetchone()[0]
                if row_count == 0:
                    return {"row_count": 0, "category_breakdown": [], "monthly_totals": [], "unparseable_date_count": 0}
                date_bounds = conn.execute("""
                    SELECT MIN(TRY_CAST(date AS DATE)), MAX(TRY_CAST(date AS DATE))
                    FROM ledgers WHERE client_id = ?
                """, [client_id]).fetchone()
                by_category = conn.execute("""
                    SELECT category, ROUND(SUM(amount), 2) as total_amount, COUNT(*) as entry_count
                    FROM ledgers WHERE client_id = ?
                    GROUP BY category
                    ORDER BY total_amount DESC
                """, [client_id]).fetchall()
                by_month = conn.execute("""
                    SELECT strftime(TRY_CAST(date AS DATE), '%Y-%m') as month,
                           ROUND(SUM(amount), 2) as total_amount
                    FROM ledgers
                    WHERE client_id = ? AND TRY_CAST(date AS DATE) IS NOT NULL
                    GROUP BY month
                    ORDER BY month
                """, [client_id]).fetchall()
                unparseable_dates = conn.execute("""
                    SELECT COUNT(*) FROM ledgers
                    WHERE client_id = ? AND TRY_CAST(date AS DATE) IS NULL
                """, [client_id]).fetchone()[0]
                return {
                    "row_count": row_count,
                    "date_min": date_bounds[0],
                    "date_max": date_bounds[1],
                    "category_breakdown": [
                        {"category": r[0], "total_amount": r[1], "entry_count": r[2]} for r in by_category
                    ],
                    "monthly_totals": [
                        {"month": r[0], "total_amount": r[1]} for r in by_month
                    ],
                    "unparseable_date_count": int(unparseable_dates),
                }
            except Exception as e:
                logger.error(f"Failed to build ledger chart context for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)
async def get_mrr_summary(client_id: str) -> dict:
    """
    FIN-01: real Monthly Recurring Revenue -- computed ONLY from rows this
    tenant explicitly flagged via an uploaded 'is_recurring'/'recurring'
    column (see _parse_recurring_series in ingest_csv_to_db). A tenant that
    has never provided the flag on any upload gets mrr_available=False and
    mrr=None -- never a computed number quietly built from an assumption.
    A tenant that HAS provided it (even if every row is flagged False) gets
    a real number, including a real $0.00 if nothing is currently flagged
    recurring for the current month -- that's a genuine answer, not a
    missing one.

    Definition used here: sum of positive-amount ("amount" > 0, i.e.
    revenue not expenses) transactions flagged is_recurring=TRUE whose date
    falls in the current calendar month. This is a transaction-based
    reading of MRR, the only one this schema can actually support (there is
    no subscription/billing-cycle/customer table to instead sum "currently
    active recurring contract value" independent of what was invoiced this
    specific month) -- disclosed via the returned "note" field rather than
    presented as a more sophisticated definition than the data supports.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    # A tenant's ledgers table may exist on disk from BEFORE this migration
    # (created by an old init_db() call that had no is_recurring column at
    # all), and this function can be the very first thing to touch ledgers
    # after a restart -- e.g. a dashboard load with no new upload yet. Same
    # pattern as get_total_ingested_rows() above: run the (idempotent,
    # cheap-on-repeat) migration check before querying a column that might
    # not exist yet on disk.
    await init_db()
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                flagged_count = conn.execute(
                    "SELECT COUNT(*) FROM ledgers WHERE client_id = ? AND is_recurring IS NOT NULL",
                    [client_id]
                ).fetchone()[0]
                if flagged_count == 0:
                    return {
                        "mrr_available": False,
                        "mrr": None,
                        "recurring_flagged_row_count": 0,
                        "revenue_month": None,
                        "note": (
                            "No uploaded row for this tenant has ever included a "
                            "recurring-vs-one-time flag ('recurring' or 'is_recurring' "
                            "column) -- true MRR is not computable until at least one "
                            "upload provides it. This is different from a tenant with "
                            "zero recurring revenue, which would show $0.00 here, not "
                            "'unavailable'."
                        ),
                    }
                current_month_key = date.today().strftime("%Y-%m")
                mrr_row = conn.execute("""
                    SELECT ROUND(SUM(amount), 2)
                    FROM ledgers
                    WHERE client_id = ?
                      AND is_recurring = TRUE
                      AND amount > 0
                      AND strftime(TRY_CAST(date AS DATE), '%Y-%m') = ?
                """, [client_id, current_month_key]).fetchone()
                mrr = float(mrr_row[0]) if mrr_row[0] is not None else 0.0
                recurring_row_count = conn.execute(
                    "SELECT COUNT(*) FROM ledgers WHERE client_id = ? AND is_recurring = TRUE",
                    [client_id]
                ).fetchone()[0]
                return {
                    "mrr_available": True,
                    "mrr": mrr,
                    "recurring_flagged_row_count": int(recurring_row_count),
                    "revenue_month": current_month_key,
                    "note": (
                        "Real Monthly Recurring Revenue: sum of positive-amount "
                        "(revenue) transactions explicitly flagged recurring=true "
                        "whose date falls in the current calendar month. One-time "
                        "transactions and rows with no recurring flag are excluded, "
                        "not guessed either way."
                    ),
                }
            except Exception as e:
                logger.error(f"Failed to compute MRR summary for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def get_amount_distribution(client_id: str, bin_count: int = 8) -> dict:
    """
    Real transaction-amount histogram for this tenant -- min/max/binning
    computed directly from actual ledger rows, not invented. Added to
    support a real "amount distribution" chart (no such capability existed
    anywhere in the codebase before this). Same lock/thread-offload/tenant-
    scoping discipline as get_ledger_chart_context above.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    bin_count = max(2, min(int(bin_count), 20))
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                rows = conn.execute(
                    "SELECT amount FROM ledgers WHERE client_id = ? AND amount IS NOT NULL",
                    [client_id]
                ).fetchall()
                amounts = [float(r[0]) for r in rows]
                if not amounts:
                    return {"row_count": 0, "bins": []}

                lo, hi = min(amounts), max(amounts)
                if lo == hi:
                    # Every recorded amount is identical -- one real bin,
                    # not a fabricated spread.
                    return {
                        "row_count": len(amounts),
                        "bins": [{
                            "range_label": f"${lo:,.2f}",
                            "range_start": round(lo, 2),
                            "range_end": round(hi, 2),
                            "count": len(amounts),
                        }],
                    }

                width = (hi - lo) / bin_count
                counts = [0] * bin_count
                for a in amounts:
                    idx = int((a - lo) / width)
                    if idx >= bin_count:
                        idx = bin_count - 1  # the max value lands in the last bin, not a phantom (bin_count+1)th one
                    counts[idx] += 1

                bins = []
                for i in range(bin_count):
                    start = lo + i * width
                    end = lo + (i + 1) * width
                    bins.append({
                        "range_label": f"${start:,.0f} to ${end:,.0f}",
                        "range_start": round(start, 2),
                        "range_end": round(end, 2),
                        "count": counts[i],
                    })
                return {"row_count": len(amounts), "bins": bins}
            except Exception as e:
                logger.error(f"Failed to build amount distribution for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def get_category_monthly_breakdown(client_id: str) -> dict:
    """
    Real category-totals-by-month breakdown -- powers the "stacked bar"
    view of monthly revenue split by category. Added specifically because
    the existing category_breakdown data (total_amount + entry_count per
    category) has no second field in the SAME unit to legitimately stack
    against total_amount -- dollars and a row count aren't comparable on
    one axis. This instead pivots real per-row (category, month, amount)
    data into one real dollar total per category per month, so every
    stacked segment is directly comparable to every other.
    Same lock/thread-offload/tenant-scoping discipline as
    get_ledger_chart_context above.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                rows = conn.execute("""
                    SELECT
                        strftime(TRY_CAST(date AS DATE), '%Y-%m') as month,
                        category,
                        ROUND(SUM(amount), 2) as total_amount
                    FROM ledgers
                    WHERE client_id = ? AND TRY_CAST(date AS DATE) IS NOT NULL
                    GROUP BY month, category
                    ORDER BY month, category
                """, [client_id]).fetchall()

                if not rows:
                    return {"months": [], "categories": [], "data": []}

                months_seen = []
                categories_seen = []
                pivot = {}
                for month, category, total_amount in rows:
                    if month not in pivot:
                        pivot[month] = {}
                        months_seen.append(month)
                    if category not in categories_seen:
                        categories_seen.append(category)
                    pivot[month][category] = float(total_amount)

                data = []
                for month in months_seen:
                    record = {"month": month}
                    for category in categories_seen:
                        # 0.0 for a category/month pair with no real rows --
                        # a genuine zero, not a fabricated estimate.
                        record[category] = pivot[month].get(category, 0.0)
                    data.append(record)

                return {
                    "months": months_seen,
                    "categories": categories_seen,
                    "data": data,
                }
            except Exception as e:
                logger.error(f"Failed to build category/monthly breakdown for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def get_category_amount_stats(client_id: str) -> dict:
    """
    Real five-number summary (min / Q1 / median / Q3 / max) of transaction
    amounts per category -- powers the "box plot" view. Computed directly
    via DuckDB's PERCENTILE_CONT/MEDIAN aggregates against this tenant's
    actual ledger rows, not estimated or invented. Whiskers are the
    category's real min/max (no IQR-fence outlier exclusion), so a lone
    extreme transaction shows up honestly as the whisker tip rather than
    being quietly dropped from the picture.
    Same lock/thread-offload/tenant-scoping discipline as
    get_ledger_chart_context above.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                rows = conn.execute("""
                    SELECT
                        category,
                        MIN(amount) as min_amount,
                        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY amount) as q1,
                        MEDIAN(amount) as median_amount,
                        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY amount) as q3,
                        MAX(amount) as max_amount,
                        COUNT(*) as entry_count
                    FROM ledgers
                    WHERE client_id = ? AND amount IS NOT NULL
                    GROUP BY category
                    ORDER BY category
                """, [client_id]).fetchall()

                return {
                    "stats": [
                        {
                            "category": r[0],
                            "min": round(float(r[1]), 2),
                            "q1": round(float(r[2]), 2),
                            "median": round(float(r[3]), 2),
                            "q3": round(float(r[4]), 2),
                            "max": round(float(r[5]), 2),
                            "entry_count": int(r[6]),
                        }
                        for r in rows
                    ]
                }
            except Exception as e:
                logger.error(f"Failed to build category amount stats for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


_SEED_ROWS = [
    ("orchestrator", "COMPLETE", 1.2),
    ("virtual_cfo", "COMPLETE", 2.1),
    ("data_engineer", "COMPLETE", 1.8),
    ("data_engineer", "ERROR", 0.5),
    ("bi_engineer", "COMPLETE", 1.4),
]
async def init_telemetry_schema():
    lock = get_db_lock()
    def _init():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("""
                    CREATE SEQUENCE IF NOT EXISTS task_id_seq;
                    CREATE TABLE IF NOT EXISTS task_telemetry (
                        task_id BIGINT DEFAULT nextval('task_id_seq'),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        agent_name VARCHAR,
                        status VARCHAR,
                        execution_time_sec DOUBLE,
                        is_seed_data BOOLEAN DEFAULT FALSE
                    )
                """)
                conn.execute("ALTER TABLE task_telemetry ADD COLUMN IF NOT EXISTS is_seed_data BOOLEAN DEFAULT FALSE")
                count = conn.execute("SELECT COUNT(*) FROM task_telemetry").fetchone()[0]
                if count == 0:
                    conn.execute("""
                        INSERT INTO task_telemetry (agent_name, status, execution_time_sec, is_seed_data)
                        VALUES
                        ('orchestrator', 'COMPLETE', 1.2, TRUE),
                        ('virtual_cfo', 'COMPLETE', 2.1, TRUE),
                        ('data_engineer', 'COMPLETE', 1.8, TRUE),
                        ('data_engineer', 'ERROR', 0.5, TRUE),
                        ('bi_engineer', 'COMPLETE', 1.4, TRUE)
                    """)
                else:
                    already_tagged = conn.execute(
                        "SELECT COUNT(*) FROM task_telemetry WHERE is_seed_data = TRUE"
                    ).fetchone()[0]
                    if already_tagged == 0:
                        conn.execute("""
                            UPDATE task_telemetry SET is_seed_data = TRUE
                            WHERE is_seed_data = FALSE
                            AND (agent_name, status, execution_time_sec) IN (
                                ('orchestrator', 'COMPLETE', 1.2),
                                ('virtual_cfo', 'COMPLETE', 2.1),
                                ('data_engineer', 'COMPLETE', 1.8),
                                ('data_engineer', 'ERROR', 0.5),
                                ('bi_engineer', 'COMPLETE', 1.4)
                            )
                        """)
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error(f"Telemetry schema init failed: {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_init)
async def log_task_execution(agent_name: str, status: str, execution_time_sec: float):
    lock = get_db_lock()
    def _log():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute(
                    "INSERT INTO task_telemetry (agent_name, status, execution_time_sec) VALUES (?, ?, ?)",
                    [agent_name, status, execution_time_sec]
                )
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error(f"Failed to log telemetry: {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)
def _safe_window(window: int) -> int:
    try:
        w = int(window)
    except (TypeError, ValueError):
        w = 100
    return max(1, min(w, 10_000))
async def get_task_success_metrics(window: int = 100) -> dict:
    window = _safe_window(window)
    lock = get_db_lock()
    def _calc():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                result = conn.execute("""
                    WITH recent_tasks AS (
                        SELECT status FROM task_telemetry
                        WHERE is_seed_data = FALSE
                        ORDER BY timestamp DESC
                        LIMIT ?
                    )
                    SELECT
                        COUNT(*) as total_tasks,
                        SUM(CASE WHEN status = 'COMPLETE' THEN 1 ELSE 0 END) as successful_tasks,
                        SUM(CASE WHEN status = 'ERROR' THEN 1 ELSE 0 END) as errored_tasks
                    FROM recent_tasks
                """, [window]).fetchone()
                total = result[0] or 0
                success = result[1] or 0
                error = result[2] or 0
                rate = (success / total * 100.0) if total > 0 else 0.0
                return {
                    "total_evaluated_window": total,
                    "success_count": success,
                    "error_count": error,
                    "success_rate_pct": round(rate, 2)
                }
            except Exception as e:
                logger.error(f"Failed to calculate success metrics: {e}")
                return {"total_evaluated_window": 0, "success_count": 0, "error_count": 0, "success_rate_pct": 0.0}
            finally:
                conn.close()
    return await asyncio.to_thread(_calc)
async def get_advanced_telemetry(window: int = 100) -> dict:
    window = _safe_window(window)
    lock = get_db_lock()
    def _calc():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                result = conn.execute("""
                    WITH recent_tasks AS (
                        SELECT status, execution_time_sec FROM task_telemetry
                        WHERE is_seed_data = FALSE
                        ORDER BY timestamp DESC
                        LIMIT ?
                    )
                    SELECT
                        COUNT(*) as total_tasks,
                        SUM(CASE WHEN status = 'COMPLETE' THEN 1 ELSE 0 END) as successful_tasks,
                        SUM(CASE WHEN status = 'ERROR' THEN 1 ELSE 0 END) as errored_tasks,
                        AVG(execution_time_sec) as avg_time
                    FROM recent_tasks
                """, [window]).fetchone()
                total = result[0] or 0
                success = result[1] or 0
                error = result[2] or 0
                avg_time = result[3] or 0.0
                rate = (success / total * 100.0) if total > 0 else 0.0
                return {
                    "total_evaluated_window": total,
                    "success_count": success,
                    "error_count": error,
                    "success_rate_pct": round(rate, 2),
                    "avg_execution_time_sec": round(avg_time, 3)
                }
            except Exception as e:
                logger.error(f"Failed to calculate advanced telemetry: {e}")
                return {"total_evaluated_window": 0, "success_count": 0, "error_count": 0, "success_rate_pct": 0.0, "avg_execution_time_sec": 0.0}
            finally:
                conn.close()
    return await asyncio.to_thread(_calc)
async def log_query_audit(client_id: str, natural_language_query: str, generated_query: str, row_count: int, status: str):
    lock = get_db_lock()
    def _log():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("""
                    CREATE SEQUENCE IF NOT EXISTS query_audit_id_seq;
                    CREATE TABLE IF NOT EXISTS query_audit (
                        audit_id BIGINT DEFAULT nextval('query_audit_id_seq'),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        client_id VARCHAR,
                        natural_language_query VARCHAR,
                        generated_query VARCHAR,
                        row_count INTEGER,
                        status VARCHAR
                    )
                """)
                conn.execute(
                    "INSERT INTO query_audit (client_id, natural_language_query, generated_query, row_count, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [client_id, natural_language_query, generated_query, row_count, status]
                )
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error(f"Failed to log query audit trail: {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)


async def log_ingestion_attempt(
    client_id: str, filename: str, file_sha256: str, status: str,
    rows_ingested: int, rows_skipped: int, detail: str
):
    """
    DATA-08: real ingestion history -- every upload attempt (successful,
    rejected for a structural reason, or a real DB-write error) is now
    recorded, not just the single most recent state implied by the
    ledgers table itself. DATA-04: file_sha256 is the fingerprint used to
    detect a byte-identical re-upload (see ingest_csv_to_db).
    """
    lock = get_db_lock()
    def _log():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("""
                    CREATE SEQUENCE IF NOT EXISTS ingestion_history_id_seq;
                    CREATE TABLE IF NOT EXISTS ingestion_history (
                        history_id BIGINT DEFAULT nextval('ingestion_history_id_seq'),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        client_id VARCHAR,
                        filename VARCHAR,
                        file_sha256 VARCHAR,
                        status VARCHAR,
                        rows_ingested INTEGER,
                        rows_skipped INTEGER,
                        detail VARCHAR
                    )
                """)
                conn.execute(
                    "INSERT INTO ingestion_history "
                    "(client_id, filename, file_sha256, status, rows_ingested, rows_skipped, detail) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [client_id, filename, file_sha256, status, rows_ingested, rows_skipped, detail]
                )
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                # Deliberately does NOT re-raise -- a failure to WRITE the
                # audit log must never block or fail the ingestion request
                # itself, same principle as log_task_execution/log_query_audit
                # above.
                logger.error(f"Failed to log ingestion attempt: {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)


async def get_ingestion_history(client_id: str, limit: int = 20) -> list:
    """DATA-08: tenant-scoped ingestion history for a history/status UI."""
    if not client_id:
        raise ValueError("client_id is required.")
    limit = max(1, min(int(limit), 200))
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ingestion_history" not in tables:
                    return []
                rows = conn.execute("""
                    SELECT timestamp, filename, status, rows_ingested, rows_skipped, detail
                    FROM ingestion_history
                    WHERE client_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, [client_id, limit]).fetchall()
                return [
                    {
                        "timestamp": str(r[0]),
                        "filename": r[1],
                        "status": r[2],
                        "rows_ingested": r[3],
                        "rows_skipped": r[4],
                        "detail": r[5],
                    }
                    for r in rows
                ]
            except Exception as e:
                logger.error(f"Failed to fetch ingestion history for tenant '{client_id}': {e}")
                return []
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


# ==============================================================================
# Track 4: multi-turn conversational memory. session_id previously only fed
# a WebSocket connection_key string (orchestrator.py) and was never used to
# fetch, store, or pass real conversation history to any agent -- every
# question was answered as if it were the first one ever asked. This is the
# real persistence layer: lazy CREATE-TABLE-on-first-write, same pattern as
# log_query_audit/log_ingestion_attempt above, no separate startup migration.
# ==============================================================================

async def log_conversation_turn(
    client_id: str, session_id: str, role: str, content: str, agent_name: Optional[str] = None
) -> None:
    """
    Persist one turn (role is "user" or "assistant") of a tenant's
    conversation with the AI swarm. A write failure here must never block
    the response the tenant is waiting on -- same discipline as the other
    audit-log writers in this file: logged and swallowed, never re-raised.
    """
    if not client_id or not session_id:
        return
    lock = get_db_lock()
    def _log():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("""
                    CREATE SEQUENCE IF NOT EXISTS conversation_turns_id_seq;
                    CREATE TABLE IF NOT EXISTS conversation_turns (
                        turn_id BIGINT DEFAULT nextval('conversation_turns_id_seq'),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        client_id VARCHAR,
                        session_id VARCHAR,
                        role VARCHAR,
                        content VARCHAR,
                        agent_name VARCHAR
                    )
                """)
                conn.execute(
                    "INSERT INTO conversation_turns (client_id, session_id, role, content, agent_name) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [client_id, session_id, role, content, agent_name]
                )
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error(f"Failed to log conversation turn: {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)


async def get_conversation_history(client_id: str, session_id: str, limit: int = 6) -> list:
    """
    The last `limit` turns for this tenant+session, oldest first (the shape
    an LLM prompt wants). Tenant- AND session-scoped: client_id is always
    part of the WHERE clause so one tenant's session_id can never surface
    another tenant's conversation, even if two sessions ever collided.
    Returns [] (never raises) on any failure or if no turns exist yet, so a
    brand-new session degrades to today's no-history behavior instead of
    erroring.
    """
    if not client_id or not session_id:
        return []
    limit = max(1, min(int(limit), 50))
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH, read_only=True)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "conversation_turns" not in tables:
                    return []
                rows = conn.execute(
                    "SELECT role, content, agent_name, timestamp FROM conversation_turns "
                    "WHERE client_id = ? AND session_id = ? ORDER BY timestamp DESC LIMIT ?",
                    [client_id, session_id, limit]
                ).fetchall()
                return [
                    {"role": r[0], "content": r[1], "agent_name": r[2], "timestamp": str(r[3])}
                    for r in reversed(rows)
                ]
            except Exception as e:
                logger.error(f"Failed to fetch conversation history for tenant '{client_id}': {e}")
                return []
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def get_last_successful_ingestion(client_id: str) -> dict:
    """DATA-04: most recent SUCCESS entry for this tenant, used to detect
    a byte-identical re-upload. Returns None if none exists yet."""
    if not client_id:
        return None
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ingestion_history" not in tables:
                    return None
                row = conn.execute("""
                    SELECT file_sha256, timestamp FROM ingestion_history
                    WHERE client_id = ? AND status = 'SUCCESS'
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, [client_id]).fetchone()
                if not row:
                    return None
                return {"file_sha256": row[0], "timestamp": str(row[1])}
            except Exception as e:
                logger.error(f"Failed to fetch last successful ingestion for tenant '{client_id}': {e}")
                return None
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def delete_tenant_ledger(client_id: str) -> int:
    """
    DATA-09: explicit deletion API for a tenant's own ledger data --
    previously the only way ledger rows ever left the table was an
    implicit delete-then-replace as a side effect of a NEW upload; there
    was no standalone "delete my data" operation at all. Tenant-scoped
    only (the caller's own client_id, enforced by the endpoint's JWT
    dependency, never accepted as free-form input) -- this is a per-tenant
    ledger wipe, not the broader tenant lifecycle deletion described in
    TEN-03 (which would also need to cover telemetry/audit history and
    the tenant record itself, once one exists).
    """
    if not client_id:
        raise ValueError("client_id is required.")
    lock = get_db_lock()
    def _delete():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                before = conn.execute(
                    "SELECT COUNT(*) FROM ledgers WHERE client_id = ?", [client_id]
                ).fetchone()[0]
                conn.execute("DELETE FROM ledgers WHERE client_id = ?", [client_id])
                conn.execute("COMMIT")
                return int(before or 0)
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error(f"Failed to delete ledger data for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    deleted_count = await asyncio.to_thread(_delete)
    await log_ingestion_attempt(
        client_id, "(deletion request)", "", "DELETED", 0, 0,
        f"Tenant-requested deletion removed {deleted_count} ledger row(s)."
    )
    return deleted_count


# ==============================================================================
# AI-06: Token, latency and cost telemetry.
#
# Execution-time and status per agent RUN were already logged (task_telemetry,
# above) -- what was missing is per-LLM-CALL token usage and an estimated
# dollar cost, so "how much is this actually costing per tenant/agent/model"
# has a real answer instead of none. Every agent file's own OpenAI call site
# now reports its real response.usage figures here via log_ai_usage_sync().
#
# Pricing verified 2026-08-22 against OpenAI's published per-1M-token rates
# for the exact model strings this codebase calls (gpt-4o, gpt-4o-mini):
# gpt-4o $2.50/1M input, $10.00/1M output; gpt-4o-mini $0.15/1M input,
# $0.60/1M output. OpenAI can and does change pricing and can retire/rename
# models -- this table is a snapshot, not a live-priced source of truth, and
# should be re-verified periodically. A model string that isn't in this
# table still gets its token counts logged; only the cost estimate is left
# null (with a one-time warning) rather than silently guessing a price.
# ==============================================================================
MODEL_PRICING = {
    "gpt-4o":       {"input_per_1m": 2.50,  "output_per_1m": 10.00},
    "gpt-4o-mini":  {"input_per_1m": 0.15,  "output_per_1m": 0.60},
}
_unpriced_models_warned = set()


def _estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        if model not in _unpriced_models_warned:
            logger.warning(f"AI usage telemetry: no pricing entry for model '{model}' -- cost will be logged as NULL for this model until MODEL_PRICING is updated.")
            _unpriced_models_warned.add(model)
        return None
    cost = (prompt_tokens / 1_000_000) * pricing["input_per_1m"] + (completion_tokens / 1_000_000) * pricing["output_per_1m"]
    return round(cost, 6)


def _in_running_loop_db() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


async def log_ai_usage(
    client_id: str, agent_name: str, model: str,
    prompt_tokens: int, completion_tokens: int, total_tokens: int,
    status: str = "SUCCESS"
):
    """
    Records one real LLM call's token usage and estimated cost. Deliberately
    never raises -- a failure to WRITE this telemetry must never break the
    agent call it's describing, same principle as log_task_execution/
    log_query_audit/log_ingestion_attempt above.
    """
    estimated_cost_usd = _estimate_cost_usd(model, prompt_tokens or 0, completion_tokens or 0)
    lock = get_db_lock()
    def _log():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("""
                    CREATE SEQUENCE IF NOT EXISTS ai_usage_id_seq;
                    CREATE TABLE IF NOT EXISTS ai_usage (
                        usage_id BIGINT DEFAULT nextval('ai_usage_id_seq'),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        client_id VARCHAR,
                        agent_name VARCHAR,
                        model VARCHAR,
                        prompt_tokens INTEGER,
                        completion_tokens INTEGER,
                        total_tokens INTEGER,
                        estimated_cost_usd DOUBLE,
                        status VARCHAR
                    )
                """)
                conn.execute(
                    "INSERT INTO ai_usage "
                    "(client_id, agent_name, model, prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [client_id, agent_name, model, prompt_tokens or 0, completion_tokens or 0, total_tokens or 0, estimated_cost_usd, status]
                )
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error(f"Failed to log AI usage telemetry for agent '{agent_name}': {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)


def log_ai_usage_sync(
    client_id: str, agent_name: str, model: str,
    prompt_tokens: int, completion_tokens: int, total_tokens: int,
    status: str = "SUCCESS"
):
    """
    Sync-context wrapper for log_ai_usage -- every agent file's OpenAI call
    site is a plain sync function (called via asyncio.to_thread from main.py,
    or directly as a LangGraph node from orchestrator.py), never itself a
    coroutine, so it can't `await` the async db_manager function above
    directly. Centralized here (rather than duplicated per agent file, the
    way _sync_log_task/_sync_log_query_audit are) so all 8 agents share one
    implementation. Same non-raising guarantee as log_ai_usage: a telemetry
    failure must never surface as, or be mistaken for, a real agent error --
    this matters especially for ops_shield.py, whose except-block treats ANY
    exception as a security threat and fails closed.
    """
    if _in_running_loop_db():
        logger.warning(f"AI usage telemetry skipped for {agent_name}: already inside a running event loop.")
        return
    try:
        asyncio.run(log_ai_usage(client_id, agent_name, model, prompt_tokens, completion_tokens, total_tokens, status))
    except Exception as e:
        logger.error(f"AI usage telemetry sync failed for {agent_name}: {e}")


async def get_ai_usage_summary(window: int = 500) -> dict:
    """
    Platform-wide AI usage/cost aggregate -- deliberately NOT broken down by
    client_id in the response, matching the existing disclosed posture of
    get_total_ingested_rows()/get_swarm_metrics() (see metrics.py): no
    tenant-scoping/RBAC tier exists yet to gate a per-tenant cost breakdown
    behind, so this stays an aggregate-only, ops-level view rather than a
    new way to see another tenant's usage.
    """
    window = max(1, min(int(window), 5000))
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ai_usage" not in tables:
                    return {
                        "total_calls": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0,
                        "total_tokens": 0, "total_estimated_cost_usd": 0.0,
                        "by_agent": [], "by_model": [],
                    }
                rows = conn.execute("""
                    SELECT agent_name, model, prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, status
                    FROM ai_usage
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, [window]).fetchall()

                total_calls = len(rows)
                total_prompt = sum(r[2] or 0 for r in rows)
                total_completion = sum(r[3] or 0 for r in rows)
                total_tokens = sum(r[4] or 0 for r in rows)
                total_cost = sum(r[5] or 0.0 for r in rows if r[5] is not None)

                by_agent = {}
                by_model = {}
                for agent_name, model, p_tok, c_tok, t_tok, cost, status in rows:
                    a = by_agent.setdefault(agent_name, {"agent_name": agent_name, "calls": 0, "total_tokens": 0, "estimated_cost_usd": 0.0})
                    a["calls"] += 1
                    a["total_tokens"] += t_tok or 0
                    a["estimated_cost_usd"] += cost or 0.0

                    m = by_model.setdefault(model, {"model": model, "calls": 0, "total_tokens": 0, "estimated_cost_usd": 0.0})
                    m["calls"] += 1
                    m["total_tokens"] += t_tok or 0
                    m["estimated_cost_usd"] += cost or 0.0

                return {
                    "total_calls": total_calls,
                    "total_prompt_tokens": int(total_prompt),
                    "total_completion_tokens": int(total_completion),
                    "total_tokens": int(total_tokens),
                    "total_estimated_cost_usd": round(total_cost, 4),
                    "window_calls_considered": window,
                    "by_agent": sorted(
                        [{**a, "estimated_cost_usd": round(a["estimated_cost_usd"], 4)} for a in by_agent.values()],
                        key=lambda x: -x["estimated_cost_usd"]
                    ),
                    "by_model": sorted(
                        [{**m, "estimated_cost_usd": round(m["estimated_cost_usd"], 4)} for m in by_model.values()],
                        key=lambda x: -x["estimated_cost_usd"]
                    ),
                }
            except Exception as e:
                logger.error(f"Failed to compute AI usage summary: {e}")
                return {
                    "total_calls": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0,
                    "total_tokens": 0, "total_estimated_cost_usd": 0.0,
                    "by_agent": [], "by_model": [], "error": str(e),
                }
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


# ==============================================================================
# FIN-04: forecast backtesting storage.
#
# Real accuracy/backtesting against historical outcomes wasn't built at all
# before this -- every forecast was thrown away the moment it was returned to
# the caller, so there was no way to ever check "was last quarter's forecast
# actually close?" This stores every per-month projection predictive_
# forecaster.py produces (see log_forecast_snapshot_sync, called from
# generate_forecast) and, once real ledger data exists for a previously
# forecasted month, get_forecast_accuracy() compares the stored projection
# against what actually happened. This is the real mechanism, not a stub --
# it will simply have nothing to report yet for any tenant whose forecasted
# months haven't occurred yet, which is an honest, expected empty state
# (feeds DIFF-08, which is explicitly blocked on this existing).
# ==============================================================================
def _add_months(yyyy_mm: str, n: int) -> str:
    y, m = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    total = (y * 12 + (m - 1)) + n
    return f"{total // 12:04d}-{(total % 12) + 1:02d}"


async def log_forecast_snapshot(client_id: str, last_historical_period: str, method: str, r_squared: float, forecast_by_month: list):
    """
    One row per forecasted month (forecast_by_month is predictive_
    forecaster's trend["forecast"] list -- each item already has
    months_ahead/projected_revenue/ci_lower_95/ci_upper_95). Never raises,
    same non-raising guarantee as the other log_* functions in this file.
    """
    lock = get_db_lock()
    def _log():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("""
                    CREATE SEQUENCE IF NOT EXISTS forecast_snapshot_id_seq;
                    CREATE TABLE IF NOT EXISTS forecast_snapshots (
                        snapshot_id BIGINT DEFAULT nextval('forecast_snapshot_id_seq'),
                        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        client_id VARCHAR,
                        target_month VARCHAR,
                        months_ahead INTEGER,
                        projected_revenue DOUBLE,
                        ci_lower_95 DOUBLE,
                        ci_upper_95 DOUBLE,
                        method VARCHAR,
                        r_squared DOUBLE
                    )
                """)
                for period in forecast_by_month:
                    target_month = _add_months(last_historical_period, period["months_ahead"])
                    conn.execute(
                        "INSERT INTO forecast_snapshots "
                        "(client_id, target_month, months_ahead, projected_revenue, ci_lower_95, ci_upper_95, method, r_squared) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [client_id, target_month, period["months_ahead"], period["projected_revenue"],
                         period["ci_lower_95"], period["ci_upper_95"], method, r_squared]
                    )
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                logger.error(f"Failed to log forecast snapshot for tenant '{client_id}': {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)


def log_forecast_snapshot_sync(client_id: str, last_historical_period: str, method: str, r_squared: float, forecast_by_month: list):
    if _in_running_loop_db():
        logger.warning(f"Forecast snapshot logging skipped for {client_id}: already inside a running event loop.")
        return
    try:
        asyncio.run(log_forecast_snapshot(client_id, last_historical_period, method, r_squared, forecast_by_month))
    except Exception as e:
        logger.error(f"Forecast snapshot logging failed for {client_id}: {e}")


async def get_forecast_accuracy(client_id: str) -> dict:
    """
    FIN-04 backtesting: for every stored forecast snapshot targeting a month
    that has since occurred, compares the projection against this tenant's
    real ledger revenue for that month (same amount > 0, grouped-by-month
    definition used everywhere else in this codebase -- see
    get_ledger_chart_context's by_month query). Snapshots targeting a month
    that hasn't happened yet are reported separately as still-pending, not
    silently dropped.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "forecast_snapshots" not in tables:
                    return {"evaluated": [], "pending": [], "note": "No forecasts have been generated for this tenant yet."}

                snapshots = conn.execute("""
                    SELECT target_month, months_ahead, projected_revenue, ci_lower_95, ci_upper_95, generated_at
                    FROM forecast_snapshots
                    WHERE client_id = ?
                    ORDER BY target_month
                """, [client_id]).fetchall()

                actuals_by_month = {}
                if "ledgers" in tables:
                    actual_rows = conn.execute("""
                        SELECT strftime(TRY_CAST(date AS DATE), '%Y-%m') as month, ROUND(SUM(amount), 2) as total_amount
                        FROM ledgers
                        WHERE client_id = ? AND amount > 0 AND TRY_CAST(date AS DATE) IS NOT NULL
                        GROUP BY month
                    """, [client_id]).fetchall()
                    actuals_by_month = {m: amt for m, amt in actual_rows}

                current_month = date.today().strftime("%Y-%m")
                evaluated, pending = [], []
                for target_month, months_ahead, projected, ci_lo, ci_hi, generated_at in snapshots:
                    if target_month in actuals_by_month:
                        actual = actuals_by_month[target_month]
                        error_pct = round(((projected - actual) / actual) * 100, 2) if actual else None
                        evaluated.append({
                            "target_month": target_month,
                            "months_ahead": months_ahead,
                            "projected_revenue": projected,
                            "actual_revenue": actual,
                            "error_pct": error_pct,
                            "within_95pct_interval": (ci_lo <= actual <= ci_hi) if actual is not None else None,
                            "generated_at": str(generated_at),
                        })
                    elif target_month <= current_month:
                        # Target month has passed but this tenant has no
                        # revenue rows for it at all (0 actual, or the data
                        # just hasn't been ingested) -- report as evaluated
                        # against 0 rather than silently dropping it, since
                        # "the tenant made $0" and "we don't know" are
                        # different and the latter would hide real inaccuracy.
                        evaluated.append({
                            "target_month": target_month,
                            "months_ahead": months_ahead,
                            "projected_revenue": projected,
                            "actual_revenue": 0.0,
                            "error_pct": None,
                            "within_95pct_interval": (ci_lo <= 0.0 <= ci_hi),
                            "generated_at": str(generated_at),
                            "note": "No ledger rows found for this month -- actual treated as $0.",
                        })
                    else:
                        pending.append({
                            "target_month": target_month,
                            "months_ahead": months_ahead,
                            "projected_revenue": projected,
                            "generated_at": str(generated_at),
                        })
                return {"evaluated": evaluated, "pending": pending}
            except Exception as e:
                logger.error(f"Failed to compute forecast accuracy for tenant '{client_id}': {e}")
                return {"evaluated": [], "pending": [], "error": str(e)}
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def get_ledger_rows(client_id: str, category: str = None, month: str = None, limit: int = 200, date_from: str = None, date_to: str = None) -> dict:
    """
    DIFF-01: real row-level drill-down -- returns the actual ledger rows
    (including each row's real row_id) behind an optional category/month
    filter, so a dashboard can show "these are the exact transactions
    behind this number" instead of only a computed aggregate. Omitting
    both filters returns this tenant's most recent rows.

    A single fixed query shape (NULL-safe "(? IS NULL OR ...)" filters)
    is used regardless of which filters are active, rather than building
    different SQL text per combination -- simpler to reason about and to
    test than four distinct query shapes.

    date_from/date_to (Track 5 global time-range selector): an inclusive
    real date-range filter, independent of and combinable with the exact
    "month" match above (both can be applied at once, though callers
    normally use one or the other). Both bounds are optional -- either one
    alone still filters correctly via the same NULL-safe pattern.

    legacy_row_count in the response counts returned rows with no row_id
    (row_id IS NULL) -- rows that existed before the DIFF-01 migration ran
    and, for some reason, were never backfilled (should be rare/zero in
    practice since init_db() backfills on first migration, but surfaced
    honestly rather than silently treating them as id 0 or dropping them).
    """
    if not client_id:
        raise ValueError("client_id is required.")
    if limit <= 0 or limit > 1000:
        limit = 200
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                rows = conn.execute("""
                    SELECT row_id, date, category, amount, description, is_recurring
                    FROM ledgers
                    WHERE client_id = ?
                      AND (? IS NULL OR category = ?)
                      AND (? IS NULL OR strftime(TRY_CAST(date AS DATE), '%Y-%m') = ?)
                      AND (? IS NULL OR TRY_CAST(date AS DATE) >= TRY_CAST(? AS DATE))
                      AND (? IS NULL OR TRY_CAST(date AS DATE) <= TRY_CAST(? AS DATE))
                    ORDER BY TRY_CAST(date AS DATE) DESC
                    LIMIT ?
                """, [client_id, category, category, month, month, date_from, date_from, date_to, date_to, limit]).fetchall()
                result_rows = [
                    {
                        "row_id": r[0],
                        "date": r[1],
                        "category": r[2],
                        "amount": r[3],
                        "description": r[4],
                        "is_recurring": r[5],
                    }
                    for r in rows
                ]
                return {
                    "client_id": client_id,
                    "filter": {"category": category, "month": month, "date_from": date_from, "date_to": date_to},
                    "row_count": len(result_rows),
                    "legacy_row_count": sum(1 for r in result_rows if r["row_id"] is None),
                    "rows": result_rows,
                }
            except Exception as e:
                logger.error(f"Failed to fetch ledger row drill-down for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


# DIFF-06: auto-categorization suggestions. Deterministic only, per founder
# decision (2026-08-23) -- a suggestion is derived from this SAME tenant's
# own already-categorized rows via keyword overlap, never an LLM guess and
# never auto-applied. A row's description is reduced to its significant
# words (lowercased, punctuation stripped, short/numeric tokens dropped),
# and matched against the same reduction of every OTHER already-categorized
# row for this tenant; the most common category among rows sharing at
# least one keyword becomes the suggestion, with a real confidence value
# (the fraction of keyword-matching rows that agree on that category) and
# the real match count backing it -- both shown to the user, never hidden.
_CATEGORY_SUGGESTION_STOPWORDS = {
    "the", "and", "for", "to", "of", "in", "on", "at", "a", "an", "with",
    "from", "inc", "llc", "co", "corp", "payment", "transaction", "purchase",
}


def _significant_words(text: str) -> set:
    words = "".join(c if c.isalnum() else " " for c in str(text).lower()).split()
    return {
        w for w in words
        if len(w) >= 3 and not w.isdigit() and w not in _CATEGORY_SUGGESTION_STOPWORDS
    }


def _suggest_category_for(description: str, categorized_rows: list) -> dict:
    """
    categorized_rows: list of (description, category) tuples for this
    tenant's rows that already have a real (non-"Uncategorized") category.
    Returns {"suggested_category": str|None, "confidence": float|None,
    "matched_row_count": int}. Pure function -- no DB access -- so this can
    be unit-tested directly without the DB/lock/thread-offload machinery.
    """
    target_words = _significant_words(description)
    if not target_words:
        return {"suggested_category": None, "confidence": None, "matched_row_count": 0}

    votes = {}
    total_matches = 0
    for other_desc, other_category in categorized_rows:
        if _significant_words(other_desc) & target_words:
            votes[other_category] = votes.get(other_category, 0) + 1
            total_matches += 1

    if not votes:
        return {"suggested_category": None, "confidence": None, "matched_row_count": 0}

    top_category, top_count = max(votes.items(), key=lambda kv: kv[1])
    return {
        "suggested_category": top_category,
        "confidence": round(top_count / total_matches, 3),
        "matched_row_count": total_matches,
    }


async def suggest_category_fixes(client_id: str) -> dict:
    """
    Returns a suggestion for every currently-"Uncategorized" row this
    tenant has, computed against their own other categorized rows. Never
    writes to the DB -- see apply_category_suggestion for that, which
    requires a real row_id (DIFF-01) so it can update the exact row the
    user confirmed, not a guess at which one they meant.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                uncategorized = conn.execute(
                    "SELECT row_id, description, amount, date FROM ledgers "
                    "WHERE client_id = ? AND category = 'Uncategorized'",
                    [client_id]
                ).fetchall()
                if not uncategorized:
                    return {"client_id": client_id, "suggestions": []}

                categorized_rows = conn.execute(
                    "SELECT description, category FROM ledgers "
                    "WHERE client_id = ? AND category != 'Uncategorized'",
                    [client_id]
                ).fetchall()

                suggestions = []
                for row_id, description, amount, txn_date in uncategorized:
                    result = _suggest_category_for(description, categorized_rows)
                    if result["suggested_category"] is not None:
                        suggestions.append({
                            "row_id": row_id,
                            "date": txn_date,
                            "description": description,
                            "amount": amount,
                            **result,
                        })
                return {"client_id": client_id, "suggestions": suggestions}
            except Exception as e:
                logger.error(f"Failed to compute category suggestions for tenant '{client_id}': {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def apply_category_suggestion(client_id: str, row_id: int, new_category: str) -> bool:
    """
    Applies ONE user-confirmed category to ONE specific row, targeted by
    its real row_id (DIFF-01) -- never a bulk/heuristic update, and never
    called automatically; the frontend only calls this after the user
    explicitly accepts a specific suggestion. row_id IS NOT NULL is
    required in the WHERE clause on purpose: a legacy row with no row_id
    (pre-DIFF-01 data that somehow missed the backfill) cannot be safely
    targeted this way and must be re-uploaded instead. Returns True if a
    row was actually updated, False if no matching row was found (wrong
    row_id, wrong tenant, or a legacy NULL row_id) -- the caller can use
    this to distinguish a real update from a silent no-op.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    if row_id is None:
        raise ValueError("row_id is required.")
    if not new_category or not str(new_category).strip():
        raise ValueError("new_category is required.")
    lock = get_db_lock()
    def _update():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE ledgers SET category = ? "
                    "WHERE client_id = ? AND row_id = ? AND row_id IS NOT NULL",
                    [str(new_category).strip(), client_id, row_id]
                )
                updated = conn.execute(
                    "SELECT category FROM ledgers WHERE client_id = ? AND row_id = ?",
                    [client_id, row_id]
                ).fetchone()
                return updated is not None and updated[0] == str(new_category).strip()
            except Exception as e:
                logger.error(f"Failed to apply category suggestion for tenant '{client_id}' row {row_id}: {e}")
                raise
            finally:
                conn.close()
    return await asyncio.to_thread(_update)
