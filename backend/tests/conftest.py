"""
Shared fixtures for the real (non-stub) backend test suite.

Design choices worth calling out:

- Every test runs against an ISOLATED, per-test DuckDB file (a fresh
  tmp_path, not backend/eivanta.duckdb) via the `isolated_db` fixture,
  which monkeypatches db_manager.DB_PATH before the test body runs. This
  suite must never touch or wipe the real tenant data file. db_manager's
  functions all read DB_PATH as a module-level global at call time (not a
  bound default argument), so monkeypatching db_manager.DB_PATH is
  sufficient -- no need to patch every call site individually.

- JWT_SECRET is set to a fixed test value in this file, at import time,
  BEFORE backend.main (and therefore backend.auth) is ever imported by any
  test module. backend/.env's real JWT_SECRET is deliberately never read
  or touched here: python-dotenv's load_dotenv() defaults to
  override=False, so setting os.environ["JWT_SECRET"] here first means
  main.py's own load_dotenv(...) call cannot clobber it.

- The `client` fixture builds a fresh FastAPI TestClient per test. Routers
  are registered once at import time inside backend/main.py's module body
  (the try/except ImportError blocks), so importing backend.main is itself
  the "app assembly" step -- done lazily inside the fixture so the
  JWT_SECRET env var above is guaranteed to be set first regardless of
  pytest's test-collection/import order.

- `auth_headers` / `make_auth_headers` give a real, live-minted JWT from
  the real account-creation path (backend.db_manager.create_tenant_and_owner
  / create_invited_user + backend.auth.hash_password) now that
  /api/v1/auth/dev-login is retired -- exercising the exact same
  verify_jwt_and_get_user() / require_role() path a real request would
  hit, not a hand-crafted token that happens to satisfy the signature
  check. See make_auth_headers's own docstring for why this calls those
  functions directly instead of going through the real HTTP
  /api/v1/auth/signup endpoint.
"""
import os
import sys
import uuid

os.environ.setdefault("JWT_SECRET", "test-suite-jwt-secret-not-for-production")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
# Real agent modules do `from openai import OpenAI` and instantiate a
# client at import time in some files -- an empty-but-present key lets
# that import succeed. No test in this suite makes a real OpenAI call
# (those are out of scope here -- see test_agent_endpoints_require_auth.py
# for why), so this key is never actually used to authenticate anything.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder-not-a-real-key")

import pytest

# Make `backend.xxx` importable the same way main.py itself expects
# (backend/main.py uses `from backend.db_manager import ...` style
# absolute imports) -- the project root (parent of backend/) must be on
# sys.path. conftest.py lives in backend/tests/, so the project root is
# two directories up.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """
    Points db_manager.DB_PATH at a throwaway DuckDB file for the duration
    of one test. Import is deferred to inside the fixture body so the
    JWT_SECRET env var above is set before backend.auth (imported
    transitively by backend.db_manager's own package) ever loads.
    """
    from backend import db_manager

    db_path = str(tmp_path / f"test_{uuid.uuid4().hex}.duckdb")
    monkeypatch.setattr(db_manager, "DB_PATH", db_path)
    return db_manager


@pytest.fixture
def app(isolated_db):
    """
    The real FastAPI app, imported fresh per test AFTER isolated_db has
    already patched db_manager.DB_PATH -- so every router that does
    `from backend.db_manager import DB_PATH` at call time (all of them;
    none cache it at import time) sees the isolated path.

    backend.main is deliberately NOT imported at module scope anywhere in
    this conftest, specifically so isolated_db's monkeypatch is always
    applied first.
    """
    import importlib

    import backend.main as main_module
    importlib.reload(main_module)  # fresh router registration per test, cheap and avoids any cross-test global state in main
    return main_module.app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_auth_headers(isolated_db):
    """
    Factory fixture: call make_auth_headers("SOME-CLIENT-ID") to mint a
    real JWT for an arbitrary tenant (role="owner" by default; pass
    role="admin"/"member"/"viewer" to test require_role() gating).

    Grounded in the REAL account-creation path
    (backend.db_manager.create_tenant_and_owner / create_invited_user +
    backend.auth.hash_password + the same JWT-claim shape
    backend/accounts.py's _mint_token uses) -- calls those functions
    directly rather than going through the real HTTP
    /api/v1/auth/signup endpoint, because signup derives client_id from
    company_name (see accounts._slugify_client_id) and tests need to
    control the exact client_id for tenant-isolation assertions.

    isolated_db is the SAME already-monkeypatched db_manager module the
    `client`/`app` fixtures' FastAPI app reads from -- pytest caches a
    fixture's result per test, so requesting isolated_db here doesn't
    create a second, differently-pointed db_manager reference.

    Idempotent per (client_id, role): a second call for a tenant/role
    that already exists in this test's isolated DB fetches the existing
    user and mints a fresh token, rather than raising, so tests can call
    this more than once for the same tenant without caring about order.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    import jwt as pyjwt

    from backend.auth import hash_password, JWT_SECRET, JWT_ALGORITHM

    def _make(client_id: str, role: str = "owner") -> dict:
        email = f"{client_id.lower()}-{role}@test.example"
        pw_hash = hash_password("test-suite-password-not-real")

        async def _get_or_create():
            existing = await isolated_db.get_user_by_email(email)
            if existing:
                return existing
            tenant = await isolated_db.get_tenant(client_id)
            if tenant is None:
                if role == "owner":
                    return await isolated_db.create_tenant_and_owner(
                        client_id, f"Test Tenant {client_id}", email, pw_hash
                    )
                # A tenant can't exist without an owner -- a non-owner
                # role requested for a brand-new client_id gets a
                # throwaway synthetic owner created first (never
                # returned to the caller), then the actually-requested
                # role is invited on top of that real tenant.
                owner_email = f"{client_id.lower()}-owner@test.example"
                if not await isolated_db.get_user_by_email(owner_email):
                    await isolated_db.create_tenant_and_owner(
                        client_id, f"Test Tenant {client_id}", owner_email,
                        hash_password("test-suite-password-not-real"),
                    )
                return await isolated_db.create_invited_user(client_id, email, pw_hash, role)
            return await isolated_db.create_invited_user(client_id, email, pw_hash, role)

        user = asyncio.run(_get_or_create())
        now = datetime.now(timezone.utc)
        payload = {
            "client_id": user["client_id"],
            "user_id": user["user_id"],
            "email": user["email"],
            "role": user["role"],
            "iat": now,
            "exp": now + timedelta(hours=1),
        }
        token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        return {"Authorization": f"Bearer {token}"}
    return _make


@pytest.fixture
def auth_headers(make_auth_headers):
    """Real JWT for tenant CLI-001, role=owner, minted via the real account-creation path."""
    return make_auth_headers("CLI-001")


def make_ledger_csv(tmp_path, rows, filename="ledger.csv", header="date,category,amount,description"):
    """
    rows: list of comma-joined data lines (already formatted) OR a list of
    tuples matching the header. Kept intentionally low-level (callers pass
    exact CSV text) so tests can construct precisely the malformed/edge-case
    files db_manager._read_csv_or_raise / ingest_csv_to_db are meant to
    handle, without a fixture abstraction hiding what's actually on disk.
    """
    path = tmp_path / filename
    lines = [header] + list(rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
