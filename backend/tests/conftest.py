"""
Shared fixtures for the real (non-stub) backend test suite.

Design choices worth calling out:

- Every test runs against an ISOLATED, per-test DuckDB file (a fresh
  tmp_path, not backend/nexusflow.duckdb) via the `isolated_db` fixture,
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

- `auth_headers` gives a real, live-minted JWT from the real
  /api/v1/auth/dev-login endpoint -- exercising the exact same
  verify_jwt_and_get_client_id() path a real request would hit, not a
  hand-crafted token that happens to satisfy the signature check.
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
def make_auth_headers(client):
    """
    Factory fixture: call make_auth_headers("SOME-CLIENT-ID") to mint a
    real JWT for an arbitrary tenant via the real dev-login endpoint.
    Exposed as a fixture (rather than a plain importable helper) so tests
    never need to reach across into conftest's module path directly --
    pytest's fixture injection handles that regardless of import-mode
    configuration.
    """
    def _make(client_id: str) -> dict:
        resp = client.post("/api/v1/auth/dev-login", json={"client_id": client_id})
        assert resp.status_code == 200, f"dev-login itself failed: {resp.text}"
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return _make


@pytest.fixture
def auth_headers(make_auth_headers):
    """Real JWT for tenant CLI-001, minted via the real dev-login endpoint."""
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
