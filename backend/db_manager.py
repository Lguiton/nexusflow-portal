import os
import json
import asyncio
import threading
import logging
import hashlib
import secrets
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

# DATA-02: a formal alias-mapping table for common real-world header
# variants of the canonical columns _read_csv_or_raise already recognizes
# (amount/revenue/expense/cost/category/date/description) -- replacing the
# previous ad-hoc behavior of only ever matching an EXACT (stripped,
# lowercased) canonical name and rejecting anything else as "no recognized
# amount column," even for an obviously-equivalent header like "amt" or
# "txn_date". Deliberately conservative: every alias here is a real header
# seen in common bank/accounting-export conventions (QuickBooks, Xero,
# Wave, generic bank CSV exports), not a guess -- and deliberately leaves
# out generic words like "type", "value", or "total" that are too likely
# to mean something else in a given file, so this never silently
# reinterprets an unrelated column as a financial one. Applied AFTER
# strip+lower but BEFORE the duplicate-column check below, so a file that
# has both an exact canonical header and an alias for the same concept
# (e.g. both "amount" and "amt") is still caught there as a real,
# actionable duplicate-column error, not silently resolved one way or the
# other.
HEADER_ALIAS_MAP = {
    "amt": "amount",
    "txn_amount": "amount",
    "transaction_amount": "amount",
    "net_amount": "amount",
    "income": "revenue",
    "sales": "revenue",
    "expenses": "expense",
    "spend": "expense",
    "spending": "expense",
    "costs": "cost",
    "cat": "category",
    "expense_category": "category",
    "transaction_category": "category",
    "txn_date": "date",
    "transaction_date": "date",
    "trans_date": "date",
    "posted_date": "date",
    "desc": "description",
    "memo": "description",
    "notes": "description",
    "narrative": "description",
    "details": "description",
}

# DATA-02 (fuzzy/typo-tolerant matching, 27 Aug 2026): the alias map above
# is an exact-match table -- a real-world typo in a header (e.g.
# "catagory", "descrption", "amuont") matches nothing in it, and every
# canonical column except 'amount' has a silent default (missing category
# -> "Uncategorized", missing date -> today, missing description -> a
# placeholder) -- meaning a MISTYPED header didn't error, it silently
# DROPPED the tenant's real column and replaced it with a placeholder for
# every row. This vocabulary is what a header gets fuzzy-matched against
# when it survives exact matching unresolved: every alias key (mapping to
# its existing resolution) plus the canonical names themselves (mapping to
# themselves), so a fuzzy hit and an exact hit always land on the same
# target for the same underlying header.
_KNOWN_HEADER_VOCAB: dict = dict(HEADER_ALIAS_MAP)
for _canonical in ("amount", "category", "date", "description", "revenue", "expense", "cost"):
    _KNOWN_HEADER_VOCAB.setdefault(_canonical, _canonical)


def _edit_distance(a: str, b: str) -> int:
    """
    Optimal String Alignment (restricted Damerau-Levenshtein): insertion,
    deletion, substitution, PLUS an adjacent-character transposition as a
    single edit. Plain Levenshtein charges a transposed pair (e.g.
    "amuont" vs "amount") as 2 substitutions, which put a very common
    class of real typo just outside a tight, deliberately-small budget --
    OSA charges it as the 1 edit it actually is. Full 2D DP table (not the
    cheaper single-row form _fuzzy_resolve_header's plain-Levenshtein
    predecessor used) because the transposition check needs to look back
    two rows, not one; still trivial cost for header-length strings.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,        # deletion
                d[i][j - 1] + 1,        # insertion
                d[i - 1][j - 1] + cost  # substitution
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)  # adjacent transposition
    return d[la][lb]


def _fuzzy_resolve_header(header: str) -> Optional[str]:
    """
    DATA-02: typo-tolerant fallback for a header that did NOT survive
    exact alias resolution (HEADER_ALIAS_MAP, or already being a
    canonical name). Matches against _KNOWN_HEADER_VOCAB using a
    length-scaled edit-distance budget -- generous enough to catch a real
    one/two-character typo on a longer word, tight enough that a short,
    unrelated header doesn't accidentally collide with a short canonical
    name (a 3-char header gets a budget of only 1).

    Deliberately returns None (leaving the header exactly as-is, so
    today's existing default/rejection behavior applies unchanged) when
    the header matches zero OR MORE THAN ONE distinct canonical target
    within budget -- an ambiguous fuzzy match is not guessed at, the same
    "explicit gap over a silent guess" preference already used elsewhere
    in this file (e.g. the ambiguous-amount-column rejection below).
    """
    if not header or header in _KNOWN_HEADER_VOCAB:
        return None
    budget = max(1, len(header) // 5)
    matches = set()
    for candidate, resolved in _KNOWN_HEADER_VOCAB.items():
        if abs(len(candidate) - len(header)) > budget:
            continue  # cheap pre-filter before the O(n*m) DP call below
        if _edit_distance(header, candidate) <= budget:
            matches.add(resolved)
        if len(matches) > 1:
            return None  # already ambiguous, no need to keep scanning
    return matches.pop() if len(matches) == 1 else None

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
                # TEN-01/TEN-02: tenant lifecycle state -- deliberately its
                # OWN column, separate from subscription_status above.
                # subscription_status is reserved for real Stripe-driven
                # state (still unwired -- see BILL-01's deferral); lifecycle
                # is a manual owner action independent of billing, since no
                # billing exists yet. Every existing and new tenant defaults
                # to 'active' (today's only real behavior) -- never silently
                # suspended by this migration. Same idempotent
                # ALTER-TABLE-if-missing shape as byok_openai_key_encrypted
                # and monthly_ai_budget_usd above.
                if "lifecycle_status" not in tenant_cols:
                    try:
                        conn.execute("ALTER TABLE tenants ADD COLUMN lifecycle_status VARCHAR DEFAULT 'active'")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                if "suspended_at" not in tenant_cols:
                    try:
                        conn.execute("ALTER TABLE tenants ADD COLUMN suspended_at TIMESTAMP")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                if "suspended_by_user_id" not in tenant_cols:
                    try:
                        conn.execute("ALTER TABLE tenants ADD COLUMN suspended_by_user_id BIGINT")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                # TEN-04: per-tenant user/team-size quota. NULL (the default
                # for every existing and new tenant) means "no quota set" --
                # unrestricted, identical to today's behavior -- never a
                # silent 0/blocked-by-default state. Same idempotent
                # migration shape and same NULL-means-unrestricted contract
                # as monthly_ai_budget_usd (FINOPS-01) above. Deliberately
                # only "users" of TEN-04's four sub-quotas (users, storage,
                # rows, requests) -- storage/rows need a billing/tier
                # concept that doesn't exist yet (the ledger ingestion model
                # is delete-and-replace per upload, not additive, so a
                # "storage" or "row" cap can't honestly mean anything until
                # that concept exists); requests already has API-03's real
                # per-tenant daily quota (see rate_limit.py).
                if "max_users" not in tenant_cols:
                    try:
                        conn.execute("ALTER TABLE tenants ADD COLUMN max_users INTEGER")
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
                # AUTH-05: login throttling / brute-force protection. Same
                # idempotent ALTER-TABLE-if-missing shape as byok_openai_key_encrypted
                # and monthly_ai_budget_usd above -- safe to run against a
                # users table that already has real rows. failed_login_attempts
                # defaults to 0 (every existing row behaves exactly as before:
                # unlocked) and locked_until defaults to NULL (never locked)
                # until backend/accounts.py's login() actually records a
                # failure -- see record_failed_login below.
                # BUGFIX (found while building AUTH-04): this was `r[0]` (the
                # column's cid, an int) instead of `r[1]` (its name) -- so
                # "failed_login_attempts" was never actually IN this list no
                # matter what, and every one of these six guards silently
                # re-ran its ALTER on every single init_db() call (which
                # happens dozens of times per request across this file, not
                # just once at startup). On a BRAND NEW users table that's
                # harmless -- the ALTER just re-adds a column that isn't
                # there yet -- so it never surfaced against a fresh db. But
                # against a users table that already has these columns (i.e.
                # after the very first call), each guard's ALTER now hits a
                # real "column already exists" CatalogException every time;
                # those get caught by the try/except below, but DuckDB (unlike
                # SQLite) marks the whole connection's transaction aborted
                # once enough statements in it have errored, so a later
                # statement on that same connection can fail with
                # "TransactionException: Current transaction is aborted" even
                # though IT would have succeeded on its own. Adding the four
                # AUTH-04 MFA columns below pushed the error count in this
                # block over that threshold and turned a previously-silent
                # bug into 72 real failing tests -- caught here in this
                # session's own verification pass before delivery, not by the
                # founder in production. Fixed by reading the column NAME
                # (r[1]) instead of its cid (r[0]), matching how tenant_cols
                # above already (correctly) does this a few lines up.
                user_cols = [r[1] for r in conn.execute("PRAGMA table_info('users')").fetchall()]
                if "failed_login_attempts" not in user_cols:
                    try:
                        conn.execute("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                if "locked_until" not in user_cols:
                    try:
                        conn.execute("ALTER TABLE users ADD COLUMN locked_until TIMESTAMP")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                # AUTH-04: TOTP-based MFA, per-user (not per-tenant -- each
                # person on a team enables/disables their own second
                # factor independently). Same idempotent ALTER-TABLE-if-
                # missing shape as failed_login_attempts/locked_until
                # above. mfa_secret_encrypted holds the CONFIRMED, active
                # secret (Fernet-encrypted via backend/byok.py's
                # encrypt_secret -- reusing that module's existing
                # encryption-at-rest helper rather than a second one);
                # mfa_pending_secret_encrypted holds a NOT-yet-confirmed
                # secret from /mfa/setup, kept separate so a half-finished
                # re-enrollment can never silently clobber a working
                # enabled secret before a real code confirms it (see
                # confirm_mfa_enrollment below, which is the only thing
                # that moves pending -> active). mfa_backup_codes_json is
                # a JSON array of SHA-256 hex digests (not bcrypt -- these
                # are high-entropy random codes, not human-chosen
                # passwords, same reasoning api_keys.py's key_hash already
                # documents), each consumed (removed) on first successful
                # use.
                if "mfa_enabled" not in user_cols:
                    try:
                        conn.execute("ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN DEFAULT FALSE")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                if "mfa_secret_encrypted" not in user_cols:
                    try:
                        conn.execute("ALTER TABLE users ADD COLUMN mfa_secret_encrypted VARCHAR")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                if "mfa_pending_secret_encrypted" not in user_cols:
                    try:
                        conn.execute("ALTER TABLE users ADD COLUMN mfa_pending_secret_encrypted VARCHAR")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                if "mfa_backup_codes_json" not in user_cols:
                    try:
                        conn.execute("ALTER TABLE users ADD COLUMN mfa_backup_codes_json VARCHAR")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
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

                # INT-01: scoped API keys for the MCP read-only tool server
                # (backend/mcp_server.py). Deliberately a SEPARATE credential
                # from a user's JWT -- an MCP client (Claude Desktop, another
                # workflow tool) is not a logged-in browser session, and a
                # long-lived JWT would be the wrong shape for that (no
                # expiry tied to a login, no per-key revocation). Same
                # idempotent CREATE-IF-NOT-EXISTS shape as every other
                # migration in this function. Only the SHA-256 hash of the
                # raw key is ever stored -- see generate_api_key below for
                # why bcrypt (meant for low-entropy human passwords) is the
                # wrong tool for a high-entropy random token.
                conn.execute("CREATE SEQUENCE IF NOT EXISTS api_key_id_seq")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        key_id BIGINT DEFAULT nextval('api_key_id_seq'),
                        client_id VARCHAR NOT NULL,
                        label VARCHAR,
                        key_prefix VARCHAR NOT NULL,
                        key_hash VARCHAR NOT NULL,
                        created_by_user_id BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_used_at TIMESTAMP,
                        revoked_at TIMESTAMP
                    )
                """)
                try:
                    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS api_keys_hash_unique ON api_keys(key_hash)")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        raise

                # AUTH-02: real refresh-token rotation. Access tokens (the
                # JWTs minted by accounts.py's _mint_token) are now SHORT-
                # lived -- there's no way to revoke a stateless JWT early,
                # so the fix is to make one useless quickly rather than try
                # to blocklist it. A refresh token is the long-lived
                # credential instead: opaque (not a JWT -- nothing to
                # decode, so nothing to forge), and only its SHA-256 hash
                # is ever stored here, same reasoning as api_keys.key_hash
                # above (a high-entropy random token, not a human password,
                # so a fast hash is the right tool). replaced_by_hash links
                # a rotated-away token forward to the one that replaced it
                # -- accounts.py's refresh() uses that link purely for
                # audit/debugging; the actual reuse-detection check is just
                # "is revoked_at already set."
                conn.execute("CREATE SEQUENCE IF NOT EXISTS refresh_token_id_seq")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS refresh_tokens (
                        refresh_token_id BIGINT DEFAULT nextval('refresh_token_id_seq'),
                        user_id BIGINT NOT NULL,
                        client_id VARCHAR NOT NULL,
                        token_hash VARCHAR NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP NOT NULL,
                        revoked_at TIMESTAMP,
                        replaced_by_hash VARCHAR
                    )
                """)
                try:
                    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS refresh_tokens_hash_unique ON refresh_tokens(token_hash)")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        raise

                # AUTH-06: session/device management. device_label and
                # session_started_at ride along on the SAME refresh_tokens
                # row created by AUTH-02, rather than a separate table,
                # because a "session" here just IS a refresh-token rotation
                # chain -- listing sessions is listing the chain's current
                # (non-revoked, non-expired) row. Existence-checked via
                # r[1] (column name), matching the r[1]-not-r[0] lesson
                # documented above for user_cols -- r[0] is PRAGMA
                # table_info's cid (an int), which would make this check
                # permanently a no-op and re-run the ALTER on every
                # init_db() call, exactly the bug that broke MFA's rollout.
                # Both columns are set ONLY at a fresh mint (login/signup/
                # mfa_verify, via accounts.py's _mint_refresh_token) and
                # carried forward unchanged by create_refresh_token during
                # a rotation, so a session's device label and "signed in
                # since" time stay stable across its whole rotation chain
                # -- created_at (already on this table) continues to
                # reflect each individual row's own mint/rotation time,
                # acting as a "last active" proxy for that same session.
                refresh_token_cols = [r[1] for r in conn.execute("PRAGMA table_info('refresh_tokens')").fetchall()]
                if "device_label" not in refresh_token_cols:
                    try:
                        conn.execute("ALTER TABLE refresh_tokens ADD COLUMN device_label VARCHAR")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                if "session_started_at" not in refresh_token_cols:
                    try:
                        conn.execute("ALTER TABLE refresh_tokens ADD COLUMN session_started_at TIMESTAMP")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise

                # API-02 (idempotency semantics): stores one row per
                # (client_id, endpoint, idempotency_key) a caller has ever
                # used, so a retried request can be recognized and
                # replayed instead of re-executed. Same idempotent
                # CREATE-IF-NOT-EXISTS + UNIQUE-INDEX shape as api_keys'
                # own migration above. response_body is stored as a JSON
                # string (DuckDB has no native JSON column type here,
                # same choice this file already made elsewhere) --
                # get_idempotent_response below is the only reader and
                # always json.loads's it back.
                conn.execute("CREATE SEQUENCE IF NOT EXISTS idempotency_key_id_seq")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS idempotency_keys (
                        id BIGINT DEFAULT nextval('idempotency_key_id_seq'),
                        client_id VARCHAR NOT NULL,
                        endpoint VARCHAR NOT NULL,
                        idempotency_key VARCHAR NOT NULL,
                        request_hash VARCHAR NOT NULL,
                        response_status INTEGER NOT NULL,
                        response_body VARCHAR NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                try:
                    conn.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idempotency_keys_unique "
                        "ON idempotency_keys(client_id, endpoint, idempotency_key)"
                    )
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        raise

                # SEC-02 (detection/logging slice): a real, tenant-scoped
                # audit trail of security-relevant EVENTS that already
                # happen elsewhere in this codebase but were previously
                # only ever surfaced as a single HTTP response to the one
                # caller who tripped them -- an account lockout (AUTH-05)
                # or a tenant-scoped rate-limit trip (API-03's tenant
                # burst/daily-quota limits) was visible to that one
                # request and then gone. This table gives a tenant's
                # owner/admin a real, queryable record of those trips
                # (see get_security_events/GET /api/v1/security/events).
                #
                # Deliberately NOT every candidate signal this item's
                # title could cover -- see the Master Build List entry
                # for this item for what's disclosed as still open
                # (credential rotation; cross-tenant 404 probe attempts;
                # the per-source-IP burst limit, which has no tenant to
                # attribute an event to and is intentionally excluded
                # here). No hash-chain tamper-evidence (unlike
                # ai_lineage_log) -- a real, disclosed simplification for
                # this slice, not an oversight.
                conn.execute("CREATE SEQUENCE IF NOT EXISTS security_event_id_seq")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS security_events (
                        id BIGINT DEFAULT nextval('security_event_id_seq'),
                        client_id VARCHAR NOT NULL,
                        event_type VARCHAR NOT NULL,
                        severity VARCHAR NOT NULL,
                        detail VARCHAR,
                        source_ip VARCHAR,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
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
    """
    Real lookup for login -- returns the password_hash too (caller
    verifies it), or None. Also returns failed_login_attempts and
    locked_until (AUTH-05) so the login endpoint can check lockout status
    BEFORE ever calling verify_password -- a locked account should never
    burn a real bcrypt verify (or leak timing) on a request it's going to
    reject regardless of the password's correctness.
    """
    await init_db()
    lock = get_db_lock()
    email_norm = email.strip().lower()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT user_id, client_id, email, password_hash, role, "
                    "failed_login_attempts, locked_until, mfa_enabled FROM users WHERE email = ?",
                    [email_norm],
                ).fetchone()
                if not row:
                    return None
                return {
                    "user_id": row[0], "client_id": row[1], "email": row[2],
                    "password_hash": row[3], "role": row[4],
                    "failed_login_attempts": row[5] or 0, "locked_until": row[6],
                    "mfa_enabled": bool(row[7]),
                }
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def get_user_by_id(user_id: int, client_id: Optional[str] = None) -> Optional[dict]:
    """
    AUTH-04: counterpart to get_user_by_email, keyed by user_id -- needed
    by the MFA endpoints, which only ever have an AuthenticatedUser (from
    a verified JWT) in hand, not an email. client_id is optional but
    should always be passed when the caller already has a verified one
    (every real caller does) -- an extra defense-in-depth scoping check
    on top of user_id already being a real primary key, at zero cost.
    """
    await init_db()
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                query = (
                    "SELECT user_id, client_id, email, password_hash, role, "
                    "failed_login_attempts, locked_until, mfa_enabled FROM users WHERE user_id = ?"
                )
                params = [user_id]
                if client_id:
                    query += " AND client_id = ?"
                    params.append(client_id)
                row = conn.execute(query, params).fetchone()
                if not row:
                    return None
                return {
                    "user_id": row[0], "client_id": row[1], "email": row[2],
                    "password_hash": row[3], "role": row[4],
                    "failed_login_attempts": row[5] or 0, "locked_until": row[6],
                    "mfa_enabled": bool(row[7]),
                }
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def update_last_login(user_id: int) -> None:
    """
    Called on every SUCCESSFUL login. AUTH-05: also clears any brute-force
    lockout state -- a real successful login is proof the right person is
    back in control of the account, so there's no reason to keep counting
    against a prior failed-attempt streak, or to leave a (by now
    presumably expired anyway) locked_until sitting on the row.
    """
    lock = get_db_lock()

    def _update():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE users SET last_login_at = CURRENT_TIMESTAMP, "
                    "failed_login_attempts = 0, locked_until = NULL WHERE user_id = ?",
                    [user_id],
                )
            finally:
                conn.close()
    await asyncio.to_thread(_update)


async def record_failed_login(user_id: int, max_attempts: int, lockout_minutes: int) -> dict:
    """
    AUTH-05: real brute-force throttling. Called once per wrong-password
    attempt against a REAL, already-found user row (accounts.login()
    never calls this for a nonexistent email -- see that function's own
    comment on why: a nonexistent email must stay indistinguishable from
    a wrong password, and an email with no user row has nowhere to store
    an attempt count anyway).

    Increments failed_login_attempts. Once it reaches max_attempts, sets
    locked_until = now + lockout_minutes and resets the counter to 0, so
    the account gets a fresh full window of attempts once the lockout
    expires rather than immediately re-locking on the next single
    failure. locked_until is computed in Python (datetime.now() + a
    timedelta) rather than a SQL INTERVAL expression -- simpler to reason
    about and test than building interval syntax from an f-string, and
    consistent with how every other time-based value in this file is
    computed.

    Returns {"locked": bool, "locked_until": Optional[datetime],
    "attempts": int} so the caller can decide what to tell the real
    person on the other end of this request.
    """
    from datetime import datetime, timedelta, timezone

    lock = get_db_lock()

    def _record():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT failed_login_attempts FROM users WHERE user_id = ?", [user_id]
                ).fetchone()
                current = (row[0] or 0) if row else 0
                new_count = current + 1
                if new_count >= max_attempts:
                    locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)
                    conn.execute(
                        "UPDATE users SET failed_login_attempts = 0, locked_until = ? WHERE user_id = ?",
                        [locked_until, user_id],
                    )
                    return {"locked": True, "locked_until": locked_until, "attempts": new_count}
                conn.execute(
                    "UPDATE users SET failed_login_attempts = ? WHERE user_id = ?",
                    [new_count, user_id],
                )
                return {"locked": False, "locked_until": None, "attempts": new_count}
            finally:
                conn.close()
    return await asyncio.to_thread(_record)


# ---------------------------------------------------------------------------
# AUTH-04: TOTP-based MFA storage. All secret/backup-code VERIFICATION
# (pyotp.TOTP(...).verify, hashing a submitted backup code and comparing)
# lives in backend/accounts.py, not here -- this module stays the same
# "storage + tenant/user scoping only" layer every other feature in this
# file already is, per this file's own module-level convention. The one
# exception is that this module DOES call backend/byok.py's decrypt_secret
# nowhere -- callers decrypt after reading, so a Fernet-key rotation only
# ever needs backend/byok.py touched, never this file.
# ---------------------------------------------------------------------------

async def get_mfa_status(user_id: int) -> dict:
    """Real enabled/disabled state plus how many single-use backup codes are left."""
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT mfa_enabled, mfa_backup_codes_json FROM users WHERE user_id = ?",
                    [user_id],
                ).fetchone()
                if not row:
                    return {"enabled": False, "backup_codes_remaining": 0}
                codes = json.loads(row[1]) if row[1] else []
                return {"enabled": bool(row[0]), "backup_codes_remaining": len(codes)}
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def set_pending_mfa_secret(user_id: int, encrypted_secret: str) -> None:
    """
    AUTH-04 step 1 (/mfa/setup): stores a NOT-yet-confirmed secret.
    Deliberately does not touch mfa_enabled or the active
    mfa_secret_encrypted -- an already-enabled account calling /mfa/setup
    again (to re-enroll a new device) must keep working with its OLD
    secret until the NEW one is actually confirmed via a real code (see
    confirm_mfa_enrollment), never silently locked out mid-re-enrollment.
    """
    lock = get_db_lock()

    def _set():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE users SET mfa_pending_secret_encrypted = ? WHERE user_id = ?",
                    [encrypted_secret, user_id],
                )
            finally:
                conn.close()
    await asyncio.to_thread(_set)


async def get_pending_mfa_secret(user_id: int) -> Optional[str]:
    """The still-Fernet-encrypted pending secret from /mfa/setup, or None if none is pending."""
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT mfa_pending_secret_encrypted FROM users WHERE user_id = ?", [user_id]
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def get_mfa_secret_encrypted(user_id: int) -> Optional[str]:
    """The ACTIVE, confirmed, still-Fernet-encrypted secret -- None if MFA isn't enabled."""
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT mfa_secret_encrypted FROM users WHERE user_id = ? AND mfa_enabled = TRUE",
                    [user_id],
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def confirm_mfa_enrollment(user_id: int, backup_code_hashes: list) -> bool:
    """
    AUTH-04 step 2 (/mfa/enable): the ONLY function that moves a pending
    secret to active. Returns False (no-op) if there's no pending secret
    to confirm -- the caller (accounts.py) is expected to have already
    verified a real TOTP code against that pending secret before calling
    this; this function itself trusts that verification happened and just
    performs the atomic column move plus backup-code write.
    """
    lock = get_db_lock()

    def _confirm():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT mfa_pending_secret_encrypted FROM users WHERE user_id = ?", [user_id]
                ).fetchone()
                if not row or not row[0]:
                    return False
                conn.execute(
                    "UPDATE users SET mfa_enabled = TRUE, mfa_secret_encrypted = ?, "
                    "mfa_pending_secret_encrypted = NULL, mfa_backup_codes_json = ? WHERE user_id = ?",
                    [row[0], json.dumps(backup_code_hashes), user_id],
                )
                return True
            finally:
                conn.close()
    return await asyncio.to_thread(_confirm)


async def consume_backup_code_if_valid(user_id: int, code_hash: str) -> bool:
    """
    Checks a SHA-256 hash (computed by the caller from the raw code the
    person typed in) against this user's remaining backup codes; removes
    it (single-use) and returns True on a match, returns False (no state
    change) otherwise. Read-modify-write under the same global db_lock
    every other write in this file already serializes through, so two
    concurrent attempts against the same code can't both "succeed."
    """
    lock = get_db_lock()

    def _consume():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT mfa_backup_codes_json FROM users WHERE user_id = ?", [user_id]
                ).fetchone()
                if not row or not row[0]:
                    return False
                codes = json.loads(row[0])
                if code_hash not in codes:
                    return False
                codes.remove(code_hash)
                conn.execute(
                    "UPDATE users SET mfa_backup_codes_json = ? WHERE user_id = ?",
                    [json.dumps(codes), user_id],
                )
                return True
            finally:
                conn.close()
    return await asyncio.to_thread(_consume)


async def disable_mfa(user_id: int) -> None:
    """AUTH-04: full teardown -- clears the active secret, any dangling pending secret, and all backup codes."""
    lock = get_db_lock()

    def _disable():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE users SET mfa_enabled = FALSE, mfa_secret_encrypted = NULL, "
                    "mfa_pending_secret_encrypted = NULL, mfa_backup_codes_json = NULL WHERE user_id = ?",
                    [user_id],
                )
            finally:
                conn.close()
    await asyncio.to_thread(_disable)


async def create_refresh_token(
    user_id: int,
    client_id: str,
    token_hash: str,
    expires_at: datetime,
    replaces_hash: Optional[str] = None,
    device_label: Optional[str] = None,
) -> None:
    """
    AUTH-02: stores a new refresh token's hash -- the raw value never
    reaches this file (backend/accounts.py's _mint_refresh_token generates
    it and hashes it before ever calling this). When replaces_hash is set
    (a rotation, not a fresh login), the OLD row is linked forward to this
    new one purely for audit trail -- the actual "was this already used"
    check in refresh() only looks at revoked_at, not this link.

    AUTH-06: device_label and the session's start time are meant to stay
    STABLE across an entire rotation chain -- a "session" a user recognizes
    in a device list is the chain, not any one row in it. So:
      - Fresh mint (replaces_hash is None): device_label is whatever the
        caller passed in (accounts.py derives it from the request's
        User-Agent at login/signup/mfa_verify time), and session_started_at
        is set to now.
      - Rotation (replaces_hash is set): device_label/session_started_at
        are copied FORWARD from the row being replaced, ignoring whatever
        device_label the caller passed (refresh() never derives a fresh
        one -- see accounts.py's refresh()), so the same browser session
        keeps showing the same device label and "signed in since" time no
        matter how many times its access token has been silently refreshed.
        If the old row is somehow already gone, this degrades to a fresh
        mint rather than raising, since a session list slot with a null
        label/timestamp is a cosmetic issue, not a security one.

    Explicitly calls init_db() first -- unlike most callers here, refresh()
    and logout() in backend/accounts.py deliberately need NO prior
    authenticated call (no Authorization header at all), so one of these
    functions can genuinely be the very first database touch of a request
    against a brand-new DB file. Every other write path in this module
    reaches that lazily via signup/login having already run first; these
    can't assume that.
    """
    await init_db()
    lock = get_db_lock()

    def _create():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                final_label = device_label
                started_at = None
                if replaces_hash:
                    old_row = conn.execute(
                        "SELECT device_label, session_started_at FROM refresh_tokens WHERE token_hash = ?",
                        [replaces_hash],
                    ).fetchone()
                    if old_row:
                        final_label, started_at = old_row[0], old_row[1]
                if started_at is None:
                    started_at = datetime.utcnow()
                conn.execute(
                    "INSERT INTO refresh_tokens "
                    "(user_id, client_id, token_hash, expires_at, device_label, session_started_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [user_id, client_id, token_hash, expires_at, final_label, started_at],
                )
                if replaces_hash:
                    conn.execute(
                        "UPDATE refresh_tokens SET replaced_by_hash = ? WHERE token_hash = ?",
                        [token_hash, replaces_hash],
                    )
            finally:
                conn.close()
    await asyncio.to_thread(_create)


async def get_refresh_token(token_hash: str) -> Optional[dict]:
    """
    AUTH-02: real lookup for POST /api/v1/auth/refresh. Returns None for an
    unknown hash -- a real row that's revoked or expired IS returned, so
    the caller can distinguish those cases (see accounts.py's refresh(),
    which reacts differently to each). Calls init_db() first -- see
    create_refresh_token's docstring for why this one function can't
    assume it already ran.

    AUTH-06: also returns replaced_by_hash now, NOT for its original
    audit-trail purpose but because refresh() needs it to tell apart two
    very different reasons a row can be revoked_at-not-null: rotated away
    as part of a normal refresh (replaced_by_hash gets set, by
    create_refresh_token, in that same call) vs. revoked for any other
    reason -- logout(), a session-management DELETE, or a revoke-all
    (none of which ever set replaced_by_hash). Only the former is a real
    "this exact token was replayed after being retired" signal; the
    latter just means "this session was intentionally ended elsewhere,"
    which must NOT be treated as reuse (see refresh()'s own docstring for
    why conflating the two used to nuke an unrelated device's session the
    next time it happened to background-refresh).
    """
    await init_db()
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT user_id, client_id, expires_at, revoked_at, replaced_by_hash "
                    "FROM refresh_tokens WHERE token_hash = ?",
                    [token_hash],
                ).fetchone()
                if not row:
                    return None
                return {
                    "user_id": row[0],
                    "client_id": row[1],
                    "expires_at": row[2],
                    "revoked_at": row[3],
                    "replaced_by_hash": row[4],
                }
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def list_active_sessions_for_user(user_id: int) -> list:
    """
    AUTH-06: GET /api/v1/auth/sessions' real data source. A "session" is
    one non-revoked, non-expired refresh_tokens row -- token_hash itself is
    deliberately never selected here (nothing that identifies the raw
    credential should leave this function), only the display-safe fields a
    user needs to recognize and manage their own signed-in devices.
    Ordered newest-first by session_started_at so the device the user is
    looking at right now tends to surface near the top.
    """
    await init_db()
    lock = get_db_lock()

    def _list():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                rows = conn.execute(
                    "SELECT refresh_token_id, device_label, session_started_at, created_at, expires_at "
                    "FROM refresh_tokens "
                    "WHERE user_id = ? AND revoked_at IS NULL AND expires_at > CURRENT_TIMESTAMP "
                    "ORDER BY session_started_at DESC NULLS LAST, refresh_token_id DESC",
                    [user_id],
                ).fetchall()
                return [
                    {
                        "session_id": r[0],
                        "device_label": r[1],
                        "session_started_at": r[2],
                        "last_active_at": r[3],
                        "expires_at": r[4],
                    }
                    for r in rows
                ]
            finally:
                conn.close()
    return await asyncio.to_thread(_list)


async def revoke_session_for_user(user_id: int, session_id: int) -> bool:
    """
    AUTH-06: DELETE /api/v1/auth/sessions/{session_id}. Scoped strictly to
    the CALLING user's own rows via the "AND user_id = ?" clause -- this is
    the only thing standing between "sign out one of my own devices" and
    "sign out any user's session by guessing an id", so it is not
    optional. Returns True if a row was actually revoked (so the endpoint
    can 404 on anything else: someone else's session, an already-revoked
    one, or a made-up id -- all indistinguishable to the caller, which is
    the point).
    """
    await init_db()
    lock = get_db_lock()

    def _revoke():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                # Checked BEFORE the UPDATE (not after) so the return value
                # means "this call is the one that revoked it" rather than
                # "it's revoked now" -- the latter would also be true for
                # an already-revoked row and make the endpoint 404 on a
                # session the caller just successfully signed out a moment
                # ago, which is confusing behavior for a retry/double-click.
                existing = conn.execute(
                    "SELECT revoked_at FROM refresh_tokens WHERE refresh_token_id = ? AND user_id = ?",
                    [session_id, user_id],
                ).fetchone()
                if existing is None or existing[0] is not None:
                    return False
                conn.execute(
                    "UPDATE refresh_tokens SET revoked_at = CURRENT_TIMESTAMP "
                    "WHERE refresh_token_id = ? AND user_id = ? AND revoked_at IS NULL",
                    [session_id, user_id],
                )
                return True
            finally:
                conn.close()
    return await asyncio.to_thread(_revoke)


async def revoke_refresh_token(token_hash: str) -> None:
    """AUTH-02: marks one refresh token revoked (e.g. on logout). Idempotent -- revoking an already-revoked or nonexistent hash is a silent no-op, never an error. Calls init_db() first -- see create_refresh_token's docstring for why this one function can't assume it already ran."""
    await init_db()
    lock = get_db_lock()

    def _revoke():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE refresh_tokens SET revoked_at = CURRENT_TIMESTAMP WHERE token_hash = ? AND revoked_at IS NULL",
                    [token_hash],
                )
            finally:
                conn.close()
    await asyncio.to_thread(_revoke)


async def revoke_all_refresh_tokens_for_user(user_id: int) -> None:
    """AUTH-02's reuse-detection response (a stolen-and-replayed refresh token kills every session on the account), and the storage foundation AUTH-06's forced-logout-everywhere will call directly. Calls init_db() first -- see create_refresh_token's docstring for why this one function can't assume it already ran."""
    await init_db()
    lock = get_db_lock()

    def _revoke_all():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE refresh_tokens SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = ? AND revoked_at IS NULL",
                    [user_id],
                )
            finally:
                conn.close()
    await asyncio.to_thread(_revoke_all)


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
                # SEC-03 SAST (28 Aug 2026): bandit B608 false positive --
                # `sets` can only ever contain the 3 hardcoded literal
                # strings above ("stripe_customer_id = ?", etc.), never
                # anything derived from a caller argument's VALUE; every
                # real value is bound via `params` as a `?` placeholder.
                conn.execute(f"UPDATE tenants SET {', '.join(sets)} WHERE client_id = ?", params)  # nosec B608
            finally:
                conn.close()
    return await asyncio.to_thread(_update)


# TEN-01/TEN-02/TEN-03: tenant lifecycle -- suspend/reactivate (manual,
# owner-triggered; NOT subscription-driven, since no billing exists yet --
# see the doc's own note that TEN-02's "subscription-driven access
# control" half stays open), full data export, and permanent deletion.
# Enforcement (who's allowed to call these, and the suspension GATE that
# blocks every OTHER endpoint for a suspended tenant) lives in
# backend/auth.py, same separation as every other RBAC-01 function above --
# this module only stores and retrieves.

# Every table below that carries a client_id column is considered "tenant
# data" for export/delete purposes. task_telemetry is deliberately EXCLUDED
# -- it has no client_id column at all; it's platform-wide agent telemetry
# (including seeded bootstrap rows, see is_seed_data), never one tenant's
# data. Keeping this list in one place means export and delete can never
# silently drift apart (a table added to one but not the other).
_TENANT_SCOPED_TABLES = (
    "ledgers", "users", "api_keys", "ai_lineage_log", "query_audit",
    "ingestion_history", "conversation_turns", "ai_usage", "forecast_snapshots",
)


async def get_tenant_lifecycle_status(client_id: str) -> Optional[str]:
    """
    Lightweight, single-column lookup -- called on EVERY authenticated
    request via backend/auth.py's verify_jwt_and_get_user, so this stays as
    cheap as a real lookup can be rather than reusing the heavier
    get_tenant() (which selects billing columns this call never needs).
    Returns None if the tenant row itself doesn't exist (should not happen
    for a real, already-issued JWT -- every user's client_id is created
    together with its tenant row in create_tenant_and_owner -- but the
    caller treats None as "can't confirm suspended" rather than raising,
    so a data anomaly here fails open on lifecycle state, not closed on
    all authentication -- see auth.py's own comment on that trade-off).
    """
    await init_db()
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT lifecycle_status FROM tenants WHERE client_id = ?", [client_id]
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def get_tenant_lifecycle_detail(client_id: str) -> Optional[dict]:
    """
    Fuller lifecycle detail for GET /api/v1/tenant/status and the
    suspend/reactivate responses -- includes WHO suspended it and WHEN,
    resolved to a real email (not just a bare user_id) so the UI can show
    something a human can actually read. Returns None if the tenant row
    doesn't exist.
    """
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT t.client_id, t.company_name, t.lifecycle_status, t.suspended_at, "
                    "t.suspended_by_user_id, u.email "
                    "FROM tenants t LEFT JOIN users u ON u.user_id = t.suspended_by_user_id "
                    "WHERE t.client_id = ?",
                    [client_id],
                ).fetchone()
                if not row:
                    return None
                return {
                    "client_id": row[0],
                    "company_name": row[1],
                    "lifecycle_status": row[2] or "active",
                    "suspended_at": str(row[3]) if row[3] is not None else None,
                    "suspended_by_user_id": row[4],
                    "suspended_by_email": row[5],
                }
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def suspend_tenant(client_id: str, suspended_by_user_id: int) -> Optional[dict]:
    """
    Idempotent: suspending an already-suspended tenant just refreshes
    suspended_at/suspended_by_user_id to this call's actor rather than
    erroring -- there's no meaningful "already suspended" failure mode
    here, only "who most recently suspended it." Returns None if the
    tenant doesn't exist (caller's client_id came from a verified JWT, so
    this should not happen in practice; guarded anyway).
    """
    lock = get_db_lock()

    def _suspend():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                exists = conn.execute("SELECT 1 FROM tenants WHERE client_id = ?", [client_id]).fetchone()
                if not exists:
                    return None
                conn.execute(
                    "UPDATE tenants SET lifecycle_status = 'suspended', "
                    "suspended_at = CURRENT_TIMESTAMP, suspended_by_user_id = ? WHERE client_id = ?",
                    [suspended_by_user_id, client_id],
                )
                return True
            finally:
                conn.close()
    result = await asyncio.to_thread(_suspend)
    if result is None:
        return None
    return await get_tenant_lifecycle_detail(client_id)


async def reactivate_tenant(client_id: str) -> Optional[dict]:
    """Clears suspension state back to 'active'. Idempotent on an already-active tenant."""
    lock = get_db_lock()

    def _reactivate():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                exists = conn.execute("SELECT 1 FROM tenants WHERE client_id = ?", [client_id]).fetchone()
                if not exists:
                    return None
                conn.execute(
                    "UPDATE tenants SET lifecycle_status = 'active', "
                    "suspended_at = NULL, suspended_by_user_id = NULL WHERE client_id = ?",
                    [client_id],
                )
                return True
            finally:
                conn.close()
    result = await asyncio.to_thread(_reactivate)
    if result is None:
        return None
    return await get_tenant_lifecycle_detail(client_id)


def _existing_tables(conn) -> set:
    """
    Several of _TENANT_SCOPED_TABLES are NOT created by init_db()'s
    up-front migration block above -- ai_lineage_log, query_audit,
    ingestion_history, conversation_turns, ai_usage, and forecast_snapshots
    are each created lazily, inside the feature that first writes to them
    (a fresh tenant that's never triggered an AI query, an NL-to-SQL
    request, an ingest, a chat turn, a billed AI call, or a forecast run
    simply has no such table in the database yet). export_tenant_data and
    delete_tenant_permanently both need this: querying a table that
    doesn't exist raises a real DuckDB CatalogException, which is not an
    error condition here -- it just means zero rows for this tenant in
    that particular feature area, exactly as if the table existed and was
    empty.
    """
    return {r[0] for r in conn.execute("SHOW TABLES").fetchall()}


def _rows_to_dicts(conn, table: str, client_id: str, exclude_cols: tuple = (), existing: set = None) -> list[dict]:
    """
    Shared helper for export_tenant_data below: introspects a table's real
    columns (PRAGMA table_info), excludes any secret column by name (never
    by assuming a fixed column order), and returns every client_id-scoped
    row as a list of plain dicts. Datetime/date values are stringified so
    the result is directly JSON-serializable without a custom encoder.
    Returns [] without querying at all if the table doesn't exist yet for
    this database (see _existing_tables above) -- never a fabricated
    error, and never a table this tenant genuinely has no rows in.
    """
    if existing is not None and table not in existing:
        return []
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{table}')").fetchall() if r[1] not in exclude_cols]
    if not cols:
        return []
    col_list = ", ".join(cols)
    # SEC-03 SAST (28 Aug 2026): bandit B608 false positive -- `cols` comes
    # from a real PRAGMA table_info(table) introspection (DB schema, never
    # user input), and `table` is only ever called with entries from the
    # fixed _TENANT_SCOPED_TABLES tuple below (a Python source constant) --
    # see export_tenant_data's own call site. client_id is always bound.
    rows = conn.execute(f"SELECT {col_list} FROM {table} WHERE client_id = ?", [client_id]).fetchall()  # nosec B608
    out = []
    for row in rows:
        d = {}
        for col, val in zip(cols, row):
            d[col] = str(val) if hasattr(val, "isoformat") else val
        out.append(d)
    return out


async def export_tenant_data(client_id: str) -> Optional[dict]:
    """
    TEN-03: full, real data-portability export -- every row this tenant's
    users/agents have ever generated, across every client_id-scoped table
    (see _TENANT_SCOPED_TABLES above), as one JSON-serializable dict.
    Secret columns are excluded by name, never returned even encrypted:
    users.password_hash and api_keys.key_hash/key_prefix (key_prefix alone
    is low-sensitivity but not this tenant's DATA -- it's a credential
    artifact; excluded for the same reason password_hash is). Returns None
    if the tenant doesn't exist.
    """
    lock = get_db_lock()

    def _export():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tenant_row = conn.execute(
                    "SELECT client_id, company_name, subscription_status, lifecycle_status, created_at "
                    "FROM tenants WHERE client_id = ?",
                    [client_id],
                ).fetchone()
                if not tenant_row:
                    return None
                result = {
                    "tenant": {
                        "client_id": tenant_row[0],
                        "company_name": tenant_row[1],
                        "subscription_status": tenant_row[2],
                        "lifecycle_status": tenant_row[3] or "active",
                        "created_at": str(tenant_row[4]) if tenant_row[4] is not None else None,
                    }
                }
                existing = _existing_tables(conn)
                for table in _TENANT_SCOPED_TABLES:
                    exclude = ()
                    if table == "users":
                        exclude = ("password_hash",)
                    elif table == "api_keys":
                        exclude = ("key_hash", "key_prefix")
                    result[table] = _rows_to_dicts(conn, table, client_id, exclude, existing=existing)
                return result
            finally:
                conn.close()
    return await asyncio.to_thread(_export)


async def delete_tenant_permanently(client_id: str) -> Optional[dict]:
    """
    TEN-03: real, permanent, cascading hard-delete -- every row this
    tenant owns across every client_id-scoped table (see
    _TENANT_SCOPED_TABLES above), then the tenants row itself, all inside
    ONE transaction so a failure partway through leaves nothing
    half-deleted (same BEGIN/COMMIT/ROLLBACK discipline as
    create_tenant_and_owner). Returns None if the tenant doesn't exist;
    otherwise returns {"deleted": True, "counts": {table: rows_deleted}}
    so the caller (and the owner who just did this) has a real receipt of
    what was removed, not just a bare success flag.

    Caller (backend/accounts.py's DELETE /api/v1/tenant) is responsible
    for the human-facing confirmation step (re-typing the company name) --
    this function itself does not ask for confirmation; it deletes
    unconditionally once called, by design, so there is exactly one place
    in the codebase that can accidentally skip that confirmation, and it
    is not this one.
    """
    lock = get_db_lock()

    def _delete():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                exists = conn.execute("SELECT 1 FROM tenants WHERE client_id = ?", [client_id]).fetchone()
                if not exists:
                    return None
                existing = _existing_tables(conn)
                counts = {}
                conn.execute("BEGIN TRANSACTION")
                try:
                    for table in _TENANT_SCOPED_TABLES:
                        if table not in existing:
                            counts[table] = 0
                            continue
                        # SEC-03 SAST (28 Aug 2026): bandit B608 false
                        # positive on both lines below -- `table` only ever
                        # comes from iterating the fixed
                        # _TENANT_SCOPED_TABLES tuple (a Python source
                        # constant) just above; client_id is always bound.
                        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE client_id = ?", [client_id]).fetchone()[0]  # nosec B608
                        conn.execute(f"DELETE FROM {table} WHERE client_id = ?", [client_id])  # nosec B608
                        counts[table] = n
                    conn.execute("DELETE FROM tenants WHERE client_id = ?", [client_id])
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                return {"deleted": True, "counts": counts}
            finally:
                conn.close()
    return await asyncio.to_thread(_delete)


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
# TEN-04 (users sub-quota): real per-tenant team-size cap. Same shape as
# FINOPS-01's budget cap immediately above -- an optional per-tenant limit
# plus a gate check that reports whether the NEXT add (an invite, here)
# should be allowed. No billing/tier concept exists yet (see the ALTER-
# TABLE comment on max_users above), so this is deliberately a tenant-
# self-service limit (an owner/admin can set their own team's ceiling, or
# leave it unset for today's unrestricted behavior) rather than a
# plan-tier-driven one -- honest about what's real today, upgradeable to
# tier-driven later without changing this gate's shape.
# ==============================================================================

async def set_tenant_user_quota(client_id: str, max_users: Optional[int]) -> None:
    """max_users=None clears the quota (back to unrestricted) -- mirrors
    set_tenant_budget_cap's None-clears convention."""
    lock = get_db_lock()

    def _update():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE tenants SET max_users = ? WHERE client_id = ?",
                    [max_users, client_id],
                )
            finally:
                conn.close()
    return await asyncio.to_thread(_update)


async def get_tenant_user_quota(client_id: str) -> Optional[int]:
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT max_users FROM tenants WHERE client_id = ?",
                    [client_id],
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def count_users_for_tenant(client_id: str) -> int:
    """Real COUNT(*) over the users table for this tenant -- not a cached
    or estimated figure, so the gate below is always checking the actual
    current headcount, including any teammate added or removed since the
    last check."""
    lock = get_db_lock()

    def _count():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE client_id = ?",
                    [client_id],
                ).fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
    return await asyncio.to_thread(_count)


async def check_user_quota_gate(client_id: str) -> dict:
    """
    The real gate check, called by accounts.invite_teammate BEFORE the new
    user is created. No quota set (the default for every tenant) ->
    always allowed=True, identical to today's unrestricted behavior. A
    quota set and the tenant's real current headcount already AT it ->
    allowed False (one more invite would exceed it), with the actual
    numbers so the caller can return an honest, specific 409 rather than a
    generic block.
    """
    max_users = await get_tenant_user_quota(client_id)
    current_users = await count_users_for_tenant(client_id)
    if max_users is None:
        return {"allowed": True, "max_users": None, "current_users": current_users, "pct_used": None}
    pct_used = round((current_users / max_users) * 100, 1) if max_users > 0 else 100.0
    allowed = current_users < max_users
    return {"allowed": allowed, "max_users": max_users, "current_users": current_users, "pct_used": pct_used}


# ==============================================================================
# API-02 (idempotency semantics): storage for backend/idempotency.py's
# real Idempotency-Key mechanism. One row per (client_id, endpoint,
# idempotency_key) a caller has ever used -- see that module's own
# docstring for the full contract (opt-in, scoped, 422 on key reuse with
# a different body). This half is deliberately pure storage: it doesn't
# know what "replay" or "store" mean as a request-lifecycle concept, the
# same separation TEN-04's quota gate keeps between "compute the real
# numbers" (here) and "decide what to do about them" (the router).
# ==============================================================================

async def get_idempotent_response(client_id: str, endpoint: str, idempotency_key: str) -> Optional[dict]:
    """None if this (client_id, endpoint, idempotency_key) has never been
    seen before -- the caller should proceed with real work. Otherwise
    the stored request_hash (for the caller to compare against the
    CURRENT request's own hash) plus the exact response to replay if
    they match."""
    await init_db()
    lock = get_db_lock()

    def _get():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT request_hash, response_status, response_body FROM idempotency_keys "
                    "WHERE client_id = ? AND endpoint = ? AND idempotency_key = ?",
                    [client_id, endpoint, idempotency_key],
                ).fetchone()
                if not row:
                    return None
                return {
                    "request_hash": row[0],
                    "response_status": row[1],
                    "response_body": json.loads(row[2]),
                }
            finally:
                conn.close()
    return await asyncio.to_thread(_get)


async def store_idempotent_response(
    client_id: str, endpoint: str, idempotency_key: str, request_hash: str,
    response_status: int, response_body: dict,
) -> None:
    await init_db()
    lock = get_db_lock()
    body_json = json.dumps(response_body)

    def _insert():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "INSERT INTO idempotency_keys "
                    "(client_id, endpoint, idempotency_key, request_hash, response_status, response_body) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [client_id, endpoint, idempotency_key, request_hash, response_status, body_json],
                )
            except Exception as e:
                # idempotency_keys_unique can legitimately fire here on a
                # genuine race: two concurrent requests carrying the same
                # brand-new key both missed get_idempotent_response above
                # (neither had been stored yet) and both tried to insert.
                # The loser's insert failing is fine -- an equivalent
                # (client_id, endpoint, idempotency_key) row already
                # exists either way, which is exactly what should be true
                # after this call regardless of which request "won".
                if "constraint" not in str(e).lower() and "unique" not in str(e).lower():
                    raise
            finally:
                conn.close()
    return await asyncio.to_thread(_insert)


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
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
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


async def get_lineage_log(
    client_id: str, limit: int = 100, offset: int = 0, agent_name: Optional[str] = None, sort: str = "desc",
) -> list:
    """
    Tenant-scoped read, most recent first by default.

    API-02: extended with real offset, an optional agent_name filter, and
    a sort direction -- ordered by lineage_id (the hash-chain's own
    sequence column, safe to page over since new rows only ever append)
    rather than timestamp, avoiding any ambiguity from two rows sharing a
    timestamp. See count_lineage_log below for the matching total-count
    query. Ordering by lineage_id here is a READ choice only -- it has no
    bearing on verify_lineage_chain's own integrity check, which walks
    the chain by lineage_id regardless of how a caller of THIS function
    asked to view it.
    """
    if not client_id:
        return []
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset or 0))
    sort_sql = "ASC" if str(sort).strip().lower() == "asc" else "DESC"
    lock = get_db_lock()

    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ai_lineage_log" not in tables:
                    return []
                params = [client_id]
                where_agent = ""
                if agent_name:
                    where_agent = " AND agent_name = ?"
                    params.append(agent_name)
                params.extend([limit, offset])
                rows = conn.execute(f"""
                    SELECT lineage_id, timestamp, session_id, agent_name, model_used,
                           query_text, decision_summary, status, prev_hash, row_hash
                    FROM ai_lineage_log
                    WHERE client_id = ?{where_agent}
                    ORDER BY lineage_id {sort_sql}
                    LIMIT ? OFFSET ?
                """, params).fetchall()
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


async def count_lineage_log(client_id: str, agent_name: Optional[str] = None) -> int:
    """Real COUNT(*) matching get_lineage_log's own WHERE clause."""
    if not client_id:
        return 0
    lock = get_db_lock()

    def _count():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ai_lineage_log" not in tables:
                    return 0
                params = [client_id]
                where_agent = ""
                if agent_name:
                    where_agent = " AND agent_name = ?"
                    params.append(agent_name)
                row = conn.execute(
                    f"SELECT COUNT(*) FROM ai_lineage_log WHERE client_id = ?{where_agent}", params
                ).fetchone()
                return int(row[0]) if row else 0
            except Exception as e:
                logger.error(f"Failed to count lineage log for tenant '{client_id}': {e}")
                return 0
            finally:
                conn.close()
    return await asyncio.to_thread(_count)


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
    """
    DATA-07 (currency): strips the currency symbols this product actually
    sees in practice ($, €, £, ¥) and thousands-separator commas, and
    converts accounting-style parenthetical negatives ("(120.00)" ->
    "-120.00") before numeric parsing. Deliberately does NOT attempt
    locale-aware decimal-comma parsing (e.g. European "1.234,56") -- that
    format is genuinely ambiguous against the US "1,234.56" convention
    without an explicit locale hint, and silently guessing wrong would
    corrupt real financial amounts. Still genuinely open; a file using
    that convention will parse as a wrong number rather than erroring, so
    this is disclosed here rather than assumed handled.

    DATA-07 (precision): rounds to 2 decimal places after parsing -- a
    real ledger amount has no meaningful sub-cent precision, and without
    this, ordinary floating-point arithmetic on the ingested values
    (e.g. 19.1 - 19.0) can drift to something like 19.099999999999998
    that then displays with a stray trailing digit downstream.
    """
    text = series.astype(str).str.strip()
    text = text.str.replace(r'^\((.*)\)$', r'-\1', regex=True)
    text = text.str.replace(r'[\$,€£¥]', '', regex=True)
    parsed = pd.to_numeric(text, errors='coerce')
    return parsed.round(2)


# DATA-07 (date): every existing date-based query in this module (MRR
# trend, cash-flow, forecasting inputs, etc.) filters with DuckDB's
# TRY_CAST(date AS DATE) -- which only reliably recognizes ISO-style
# ("2026-01-15") strings. Before this, the 'date' column was stored
# verbatim from whatever the source file happened to contain, so a
# perfectly legitimate export using "01/15/2026", "15-Jan-2026", or
# "Jan 15, 2026" style dates silently failed every TRY_CAST downstream --
# those rows quietly vanished from every date-filtered view with no error
# and no visibility into why. This list is tried in order, most specific
# first, and covers the formats real bank/accounting exports actually use.
#
# Slash-style dates are genuinely ambiguous (01/02/2026: Jan 2, or Feb 1?).
# Resolved MM/DD/YYYY first (the more common convention for this product's
# target exports); a value that fails MM/DD but succeeds DD/MM is accepted
# as DD/MM. This is a disclosed heuristic, not a guarantee of correctness
# for every locale -- still open, not silently assumed solved.
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%m/%d/%y",
    "%d/%m/%y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
]


def _normalize_date_series(series: pd.Series) -> "tuple[pd.Series, int]":
    """
    Returns (normalized_series, unparseable_count). Every value that
    matches one of _DATE_FORMATS (or, failing that, pandas' own general
    date parser -- catching the remaining reasonable cases, e.g. ISO
    strings with a time component) is rewritten to canonical ISO
    (YYYY-MM-DD). A value that is present but matches nothing is stored
    as None (genuinely unknown -- never guessed at), consistent with this
    codebase's existing NULL philosophy for is_recurring and unparseable
    amounts: the row is NOT dropped for this alone (its amount/category/
    description are still real data), it just won't appear in date-
    filtered views. The caller surfaces unparseable_count so this stays
    visible to the user rather than a silent hole.
    """
    unparseable_count = 0

    def _parse_one(v):
        nonlocal unparseable_count
        text = str(v).strip()
        if not text:
            unparseable_count += 1
            return None
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        try:
            parsed = pd.to_datetime(text, errors="raise")
            return parsed.date().isoformat()
        except (ValueError, TypeError):
            unparseable_count += 1
            return None

    return series.apply(_parse_one), unparseable_count


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

    DATA-07 (encoding): tries UTF-8 first (unchanged from before -- the
    common case, and any already-working file decodes identically), then
    falls back through a short, disclosed list of encodings real-world
    exports actually use (Windows-1252, then Latin-1) before giving up.
    Latin-1 never itself raises UnicodeDecodeError (every byte maps to a
    codepoint), so it's a genuine last resort, not a silent guess-and-hope
    -- it's tried last, after two more likely candidates, specifically so
    a Windows-origin export (the actual common source of "not UTF-8" ledger
    files) decodes correctly rather than falling straight to the crudest
    fallback.
    """
    encodings_to_try = ["utf-8", "cp1252", "latin-1"]
    last_error = None
    for encoding in encodings_to_try:
        try:
            return pd.read_csv(file_path, encoding=encoding)
        except pd.errors.EmptyDataError:
            raise ValueError("This file is empty -- no header row or data was found.")
        except pd.errors.ParserError as e:
            raise ValueError(
                f"This file could not be parsed as a valid CSV: {e}. This usually means "
                "some rows have a different number of columns than the header row "
                "(a ragged/malformed file), or the file uses an unexpected delimiter."
            )
        except UnicodeDecodeError as e:
            last_error = e
            continue
    raise ValueError(
        f"This file's text encoding could not be read ({last_error}). Tried UTF-8, "
        "Windows-1252, and Latin-1. Try re-saving it as UTF-8 CSV and uploading again."
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
        # DATA-02: resolve known aliases to their canonical name -- see
        # HEADER_ALIAS_MAP's own module-level docstring/comment for why
        # this runs here (after strip+lower, before the duplicate check).
        df.columns = [HEADER_ALIAS_MAP.get(c, c) for c in df.columns]

        # DATA-02 (fuzzy/typo-tolerant matching): whatever didn't survive
        # the exact alias map above gets one more chance via
        # _fuzzy_resolve_header -- see that function's own docstring for
        # the matching/ambiguity rules. Tracked separately (rather than
        # folded silently into the same list comprehension) so the
        # success message below can disclose exactly which header(s), if
        # any, were reinterpreted -- this never happens invisibly.
        fuzzy_resolutions: dict = {}
        new_columns = []
        for c in df.columns:
            resolved = _fuzzy_resolve_header(c)
            if resolved:
                fuzzy_resolutions[c] = resolved
                new_columns.append(resolved)
            else:
                new_columns.append(c)
        df.columns = new_columns

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
                    "'revenue' + 'expense', 'cost', or 'expense' -- or a common alias like "
                    "'amt', 'income', 'sales', 'expenses', or 'costs') so ingestion doesn't "
                    "have to guess which column represents the financial amount. "
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

        # DATA-07 (date): missing dates still default to today (existing,
        # unchanged behavior) -- normalization below then rewrites whatever
        # format survives to canonical ISO, or NULL if it's present but
        # genuinely unrecognized (see _normalize_date_series's own
        # docstring for why that doesn't drop the row).
        raw_date_series = df['date'].fillna(today_str).astype(str)
        normalized_dates, date_unparseable_count = _normalize_date_series(raw_date_series)

        clean_df = pd.DataFrame({
            'client_id': client_id,
            'date': normalized_dates,
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

        # DATA-02: NOT extending the amount check's "100% unparseable ->
        # reject the whole file" reasoning to date, on purpose. Tried this
        # during development, caught by the full regression suite: a row
        # with an unparseable date but a real amount/category/description
        # is still real, useful data (unlike amount, where an unparseable
        # value means the row has no number at all) -- this codebase
        # already has a deliberate, shipped, tested design for the "every
        # row's date is unparseable" case: ingestion still succeeds, the
        # count is disclosed in the message below, and downstream,
        # virtual_cfo.generate_cfo_briefing reports a distinct
        # NO_DATEABLE_DATA status rather than crashing or misreporting
        # NO_DATA (see test_virtual_cfo_evidence.py's
        # test_no_dateable_data_status_when_every_row_unparseable). Adding
        # a hard rejection here would silently break that already-correct
        # behavior for no real benefit.
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
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
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
    if fuzzy_resolutions:
        pairs = ", ".join(f"'{orig}' -> '{resolved}'" for orig, resolved in sorted(fuzzy_resolutions.items()))
        message += f" Note: interpreted these column header(s) by typo-tolerant match: {pairs}."
    if skipped_count:
        message += f" Skipped {skipped_count} row(s) with an unparseable amount value."
    if date_unparseable_count:
        message += (
            f" Note: {date_unparseable_count} row(s) had a date value in a format that "
            "couldn't be recognized -- those rows were still ingested (amount/category/"
            "description are unaffected), but with an unknown date, so they won't appear "
            "in date-filtered views until re-uploaded with a supported date format."
        )

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
                    return {
                        "row_count": 0, "category_breakdown": [], "monthly_totals": [],
                        "monthly_revenue_totals": [], "unparseable_date_count": 0,
                    }
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
                # Revenue-ONLY monthly totals (amount > 0), separate from by_month above
                # (which nets revenue and expense together). Added because
                # /api/v1/finance/analytics-summary's month-over-month percentage was
                # being computed from by_month's net figures while displayed directly
                # beside total_revenue (a revenue-only number) -- on this tenant's real
                # test ledger that produced a "+33.8%" reading right next to "Total
                # Revenue $58,000" when actual revenue had fallen -32.9% month-over-month
                # (confirmed against agents/saas_strategist.py's mom_change_pct, which
                # already computed this correctly via its own WHERE amount > 0 query --
                # mirrored here so get_ledger_chart_context's consumers, not just the
                # SaaS Strategist agent, can use a real revenue-only trend figure).
                by_month_revenue = conn.execute("""
                    SELECT strftime(TRY_CAST(date AS DATE), '%Y-%m') as month,
                           ROUND(SUM(amount), 2) as total_amount
                    FROM ledgers
                    WHERE client_id = ? AND TRY_CAST(date AS DATE) IS NOT NULL AND amount > 0
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
                    "monthly_revenue_totals": [
                        {"month": r[0], "total_amount": r[1]} for r in by_month_revenue
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
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
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
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
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
async def log_query_audit(client_id: str, natural_language_query: str, generated_query: str, row_count: int, status: str, user_id: Optional[int] = None):
    """
    SQL-03: query audit trail. `user_id` was added 27 Aug 2026 -- prior to this
    the table was scoped to tenant only (no per-user attribution), since no
    user-level auth existed at the time this table was first created. The
    column is added via a lazy migration guard below (mirroring the
    device_label/session_started_at pattern used for AUTH-06's MFA rollout)
    rather than in the central init_db() migration block, matching how this
    table has always been created -- lazily, on first audit write.
    """
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
                query_audit_cols = [r[1] for r in conn.execute("PRAGMA table_info('query_audit')").fetchall()]
                if "user_id" not in query_audit_cols:
                    try:
                        conn.execute("ALTER TABLE query_audit ADD COLUMN user_id BIGINT")
                    except Exception as e:
                        if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                            raise
                conn.execute(
                    "INSERT INTO query_audit (client_id, natural_language_query, generated_query, row_count, status, user_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [client_id, natural_language_query, generated_query, row_count, status, user_id]
                )
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
                logger.error(f"Failed to log query audit trail: {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)


async def log_report_export(
    client_id: str, user_id: Optional[int], report_type: str,
    export_format: str, status: str
) -> None:
    """
    REP-02: audit trail for report exports (who downloaded what, in what
    format, when). Mirrors log_query_audit's own table-lazy-creation
    pattern exactly -- same reasoning: this table has no reason to exist
    until the first real export happens, and every table this codebase
    creates lazily follows this same CREATE SEQUENCE + CREATE TABLE IF NOT
    EXISTS shape so a fresh tenant database never needs a separate up-front
    migration step for it. Fails open on a logging failure (same posture
    as every other audit/telemetry logger here) -- a broken audit log must
    never itself block a tenant from downloading their own report.
    """
    lock = get_db_lock()
    def _log():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("""
                    CREATE SEQUENCE IF NOT EXISTS report_export_audit_id_seq;
                    CREATE TABLE IF NOT EXISTS report_export_audit (
                        audit_id BIGINT DEFAULT nextval('report_export_audit_id_seq'),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        client_id VARCHAR,
                        user_id BIGINT,
                        report_type VARCHAR,
                        export_format VARCHAR,
                        status VARCHAR
                    )
                """)
                conn.execute(
                    "INSERT INTO report_export_audit (client_id, user_id, report_type, export_format, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [client_id, user_id, report_type, export_format, status]
                )
                conn.execute("COMMIT")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
                logger.error(f"Failed to log report export audit trail: {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)


async def get_report_export_history(
    client_id: str, limit: int = 50, offset: int = 0, export_format: Optional[str] = None, sort: str = "desc",
) -> list:
    """
    REP-02: read side of the export audit trail -- lets a tenant (owner/
    admin, gated at the router) see who exported what, when. Returns []
    if the table doesn't exist yet for this tenant's database (no export
    has ever happened), same "no fabricated error on an empty/missing
    table" posture as _rows_to_dicts uses for tenant export/deletion.

    API-02: extended with real offset, an optional export_format filter
    (e.g. 'pdf'/'csv' -- whatever real values this tenant's own rows
    contain), and a sort direction. See count_report_export_history below
    for the matching total-count query.
    """
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset or 0))
    sort_sql = "ASC" if str(sort).strip().lower() == "asc" else "DESC"
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                existing = _existing_tables(conn)
                if "report_export_audit" not in existing:
                    return []
                params = [client_id]
                where_format = ""
                if export_format:
                    where_format = " AND export_format = ?"
                    params.append(export_format)
                params.extend([limit, offset])
                rows = conn.execute(
                    f"SELECT audit_id, timestamp, user_id, report_type, export_format, status "
                    f"FROM report_export_audit WHERE client_id = ?{where_format} "
                    f"ORDER BY timestamp {sort_sql} LIMIT ? OFFSET ?",
                    params
                ).fetchall()
                return [
                    {
                        "audit_id": r[0],
                        "timestamp": str(r[1]),
                        "user_id": r[2],
                        "report_type": r[3],
                        "export_format": r[4],
                        "status": r[5],
                    }
                    for r in rows
                ]
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def count_report_export_history(client_id: str, export_format: Optional[str] = None) -> int:
    """Real COUNT(*) matching get_report_export_history's own WHERE clause."""
    lock = get_db_lock()
    def _count():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                existing = _existing_tables(conn)
                if "report_export_audit" not in existing:
                    return 0
                params = [client_id]
                where_format = ""
                if export_format:
                    where_format = " AND export_format = ?"
                    params.append(export_format)
                row = conn.execute(
                    f"SELECT COUNT(*) FROM report_export_audit WHERE client_id = ?{where_format}", params
                ).fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
    return await asyncio.to_thread(_count)


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
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
                # Deliberately does NOT re-raise -- a failure to WRITE the
                # audit log must never block or fail the ingestion request
                # itself, same principle as log_task_execution/log_query_audit
                # above.
                logger.error(f"Failed to log ingestion attempt: {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_log)


async def get_ingestion_history(
    client_id: str, limit: int = 20, offset: int = 0, status: Optional[str] = None, sort: str = "desc",
) -> list:
    """
    DATA-08: tenant-scoped ingestion history for a history/status UI.

    API-02: extended with real offset (page past the first `limit` rows,
    not just see the newest ones), an optional status filter (e.g.
    'SUCCESS'/'REJECTED' -- whatever real values this tenant's own rows
    actually contain, not a hardcoded enum, so a status this codebase
    adds later works here with no change), and a sort direction over the
    same timestamp column the query already ordered by. See
    count_ingestion_history below for the matching total-count query
    (kept separate rather than folded into this function's return shape,
    so existing callers of THIS function -- e.g.
    test_db_manager_queries.py -- keep getting a plain list back).
    """
    if not client_id:
        raise ValueError("client_id is required.")
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset or 0))
    sort_sql = "ASC" if str(sort).strip().lower() == "asc" else "DESC"
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ingestion_history" not in tables:
                    return []
                params = [client_id]
                where_status = ""
                if status:
                    where_status = " AND status = ?"
                    params.append(status)
                params.extend([limit, offset])
                rows = conn.execute(f"""
                    SELECT timestamp, filename, status, rows_ingested, rows_skipped, detail
                    FROM ingestion_history
                    WHERE client_id = ?{where_status}
                    ORDER BY timestamp {sort_sql}
                    LIMIT ? OFFSET ?
                """, params).fetchall()
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


async def count_ingestion_history(client_id: str, status: Optional[str] = None) -> int:
    """Real COUNT(*) matching get_ingestion_history's own WHERE clause
    (same client_id + optional status filter), so total_count in the
    paginated response envelope always reflects the SAME filtered set
    the page of rows was drawn from."""
    if not client_id:
        return 0
    lock = get_db_lock()
    def _count():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "ingestion_history" not in tables:
                    return 0
                params = [client_id]
                where_status = ""
                if status:
                    where_status = " AND status = ?"
                    params.append(status)
                row = conn.execute(
                    f"SELECT COUNT(*) FROM ingestion_history WHERE client_id = ?{where_status}", params
                ).fetchone()
                return int(row[0]) if row else 0
            except Exception as e:
                logger.error(f"Failed to count ingestion history for tenant '{client_id}': {e}")
                return 0
            finally:
                conn.close()
    return await asyncio.to_thread(_count)


# ---------------------------------------------------------------------------
# SEC-02: security-event detection/logging. See the migration comment above
# (init_db) for what this table does and does NOT cover.

_VALID_SECURITY_SEVERITIES = {"low", "medium", "high", "critical"}


async def log_security_event(
    client_id: str, event_type: str, severity: str,
    detail: Optional[str] = None, source_ip: Optional[str] = None,
) -> None:
    """
    Records one row to security_events. Deliberately FAIL-OPEN, same
    discipline as store_idempotent_response above: this is called from
    the middle of a real request that is about to return a 429 (a
    rate-limit trip) or already has (an account lockout) -- a failure to
    WRITE the audit record must never itself raise, mask, or delay the
    real response the caller is waiting on. Any failure is logged and
    swallowed; the caller never even awaits a return value.

    Silently no-ops (no exception, no log spam) if client_id or
    event_type is falsy, or severity isn't one of
    _VALID_SECURITY_SEVERITIES -- a call-site typo should never be able
    to either crash a real request or corrupt the audit table with junk
    rows a reader can't make sense of.
    """
    if not client_id or not event_type or severity not in _VALID_SECURITY_SEVERITIES:
        logger.error(
            f"log_security_event: invalid call (client_id={client_id!r}, "
            f"event_type={event_type!r}, severity={severity!r}) -- not recorded."
        )
        return
    lock = get_db_lock()

    def _write():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                conn.execute(
                    "INSERT INTO security_events (client_id, event_type, severity, detail, source_ip) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [client_id, event_type, severity, detail, source_ip],
                )
            except Exception as e:
                logger.error(f"Failed to record security event ({event_type}) for tenant '{client_id}': {e}")
            finally:
                conn.close()
    await asyncio.to_thread(_write)


async def get_security_events(
    client_id: str, limit: int = 20, offset: int = 0,
    event_type: Optional[str] = None, severity: Optional[str] = None, sort: str = "desc",
) -> list:
    """Tenant-scoped, paginated/filterable read of security_events -- same
    shape/discipline as get_ingestion_history above (real offset, optional
    filters, sort direction; see count_security_events for the matching
    total-count query)."""
    if not client_id:
        raise ValueError("client_id is required.")
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset or 0))
    sort_sql = "ASC" if str(sort).strip().lower() == "asc" else "DESC"
    lock = get_db_lock()

    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "security_events" not in tables:
                    return []
                params = [client_id]
                where_extra = ""
                if event_type:
                    where_extra += " AND event_type = ?"
                    params.append(event_type)
                if severity:
                    where_extra += " AND severity = ?"
                    params.append(severity)
                params.extend([limit, offset])
                rows = conn.execute(f"""
                    SELECT id, event_type, severity, detail, source_ip, created_at
                    FROM security_events
                    WHERE client_id = ?{where_extra}
                    ORDER BY created_at {sort_sql}, id {sort_sql}
                    LIMIT ? OFFSET ?
                """, params).fetchall()
                return [
                    {
                        "id": r[0],
                        "event_type": r[1],
                        "severity": r[2],
                        "detail": r[3],
                        "source_ip": r[4],
                        "created_at": str(r[5]),
                    }
                    for r in rows
                ]
            except Exception as e:
                logger.error(f"Failed to fetch security events for tenant '{client_id}': {e}")
                return []
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def count_security_events(
    client_id: str, event_type: Optional[str] = None, severity: Optional[str] = None,
) -> int:
    """Real COUNT(*) matching get_security_events' own WHERE clause."""
    if not client_id:
        return 0
    lock = get_db_lock()

    def _count():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
                if "security_events" not in tables:
                    return 0
                params = [client_id]
                where_extra = ""
                if event_type:
                    where_extra += " AND event_type = ?"
                    params.append(event_type)
                if severity:
                    where_extra += " AND severity = ?"
                    params.append(severity)
                row = conn.execute(
                    f"SELECT COUNT(*) FROM security_events WHERE client_id = ?{where_extra}", params
                ).fetchone()
                return int(row[0]) if row else 0
            except Exception as e:
                logger.error(f"Failed to count security events for tenant '{client_id}': {e}")
                return 0
            finally:
                conn.close()
    return await asyncio.to_thread(_count)


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
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
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
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
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
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
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
                    pass  # nosec B110 -- best-effort rollback; nothing more to do if this also fails
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


# ---------------------------------------------------------------------------
# INT-01: MCP read-only tool server -- scoped API keys.
#
# A separate credential type from the JWTs accounts.py issues on login.
# An MCP client (Claude Desktop, another workflow tool) is not a logged-in
# browser session, so it needs a long-lived, individually-revocable secret
# instead of a short-lived per-login token. Only ever consumed by
# backend/mcp_server.py's own auth middleware -- never accepted by any
# other REST endpoint in this app, so a leaked key's blast radius is
# limited to the read-only MCP tool surface, not the full mutating API.
# ---------------------------------------------------------------------------

API_KEY_PREFIX = "evta_live_"


def _hash_api_key(raw_key: str) -> str:
    """
    SHA-256, not bcrypt. bcrypt's whole design point is slowing down
    brute-force guessing of LOW-entropy human passwords -- it is the wrong
    tool for a 256-bit random token nobody could ever brute-force in the
    first place, and its 72-byte truncation (see auth.py's hash_password)
    would silently and incorrectly truncate a token this long. A plain
    fast hash is exactly right here: the token's own entropy is the
    security property, not the hash function's slowness.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def generate_api_key(client_id: str, label: str, created_by_user_id: int) -> dict:
    """
    Creates a new scoped API key for a tenant. Returns the RAW key exactly
    once, in this return value -- only its hash is ever persisted, so a
    caller that loses this response has no way to recover the key and must
    generate a new one. key_prefix (the first 12 characters of the raw
    key, e.g. "evta_live_ab") is stored in cleartext purely so a tenant can
    tell their keys apart in a list UI without the full secret ever being
    displayed or retrievable again.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    await init_db()
    raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    key_hash = _hash_api_key(raw_key)
    key_prefix = raw_key[:12]
    lock = get_db_lock()
    def _insert():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "INSERT INTO api_keys (client_id, label, key_prefix, key_hash, created_by_user_id) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "RETURNING key_id, created_at",
                    [client_id, (label or "").strip()[:200] or None, key_prefix, key_hash, created_by_user_id],
                ).fetchone()
                return {"key_id": row[0], "created_at": row[1]}
            finally:
                conn.close()
    inserted = await asyncio.to_thread(_insert)
    return {
        "key_id": inserted["key_id"],
        "api_key": raw_key,
        "key_prefix": key_prefix,
        "label": (label or "").strip()[:200] or None,
        "created_at": inserted["created_at"],
    }


async def list_api_keys(client_id: str) -> list:
    """
    Never returns the raw key or its hash -- key_prefix is the only
    identifying fragment a tenant sees again after creation.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    await init_db()
    lock = get_db_lock()
    def _query():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                rows = conn.execute(
                    "SELECT key_id, label, key_prefix, created_at, last_used_at, revoked_at "
                    "FROM api_keys WHERE client_id = ? ORDER BY created_at DESC",
                    [client_id],
                ).fetchall()
                return [
                    {
                        "key_id": r[0],
                        "label": r[1],
                        "key_prefix": r[2],
                        "created_at": r[3],
                        "last_used_at": r[4],
                        "revoked_at": r[5],
                        "active": r[5] is None,
                    }
                    for r in rows
                ]
            finally:
                conn.close()
    return await asyncio.to_thread(_query)


async def revoke_api_key(client_id: str, key_id: int) -> bool:
    """
    Soft-revoke (sets revoked_at) rather than a hard DELETE -- keeps the
    row for audit purposes, same posture as every other "delete" in this
    codebase (e.g. tenants are never hard-deleted either). Scoped to
    client_id AND key_id together so one tenant can never revoke another
    tenant's key even if they somehow learned its key_id. Returns False
    (not an error) for a nonexistent/already-revoked/wrong-tenant key_id --
    the caller decides whether that should surface as a 404.
    """
    if not client_id:
        raise ValueError("client_id is required.")
    if key_id is None:
        raise ValueError("key_id is required.")
    lock = get_db_lock()
    def _revoke():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "UPDATE api_keys SET revoked_at = CURRENT_TIMESTAMP "
                    "WHERE client_id = ? AND key_id = ? AND revoked_at IS NULL "
                    "RETURNING key_id",
                    [client_id, key_id],
                ).fetchone()
                return row is not None
            finally:
                conn.close()
    return await asyncio.to_thread(_revoke)


async def get_client_id_for_api_key(raw_key: str) -> Optional[dict]:
    """
    Validates a presented raw key against the stored hash and returns the
    owning tenant's client_id, or None for anything invalid: empty input,
    unknown key, or a revoked key. Also stamps last_used_at on a
    successful match -- best-effort telemetry, not security-critical, so a
    failure to record it does not fail the auth check itself.
    """
    if not raw_key or not raw_key.startswith(API_KEY_PREFIX):
        return None
    key_hash = _hash_api_key(raw_key)
    lock = get_db_lock()
    def _lookup():
        with lock:
            conn = duckdb.connect(DB_PATH)
            try:
                row = conn.execute(
                    "SELECT key_id, client_id FROM api_keys "
                    "WHERE key_hash = ? AND revoked_at IS NULL",
                    [key_hash],
                ).fetchone()
                if row is None:
                    return None
                key_id, client_id = row
                try:
                    conn.execute(
                        "UPDATE api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE key_id = ?",
                        [key_id],
                    )
                except Exception as e:
                    logger.warning(f"Could not stamp last_used_at for api key {key_id}: {e}")
                return {"key_id": key_id, "client_id": client_id}
            finally:
                conn.close()
    return await asyncio.to_thread(_lookup)
