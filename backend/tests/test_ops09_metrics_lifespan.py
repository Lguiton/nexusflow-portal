"""
OPS-09 (27 Aug 2026): metrics.py's telemetry-schema init used to run via
the deprecated `@router.on_event("startup")` FastAPI hook. That hook is
gone -- init now happens inside backend/main.py's app-level `lifespan`
context manager (the same one INT-01's MCP session manager already used),
gated on a new `_metrics_router_loaded` flag so the behavior matches the
old on_event handler exactly: only fires if the metrics router actually
loaded, and only once, after the real event loop is live.

These tests lock in that the migration didn't change any real behavior --
not just that the code compiles, but that the schema genuinely gets
initialized before the first request can reach it, via the new mechanism.
"""
import importlib

import duckdb


def test_metrics_router_has_no_on_event_startup_handler():
    """The old @router.on_event("startup") hook must actually be gone, not
    just unused -- if a future edit reintroduces it, APIRouter's own
    on_startup list is the ground truth (that's exactly where FastAPI
    stashes on_event-registered handlers before merging them into the app
    on include_router)."""
    from backend import metrics

    assert metrics.router.on_startup == [], (
        "metrics.router still has a startup event handler registered -- "
        "OPS-09 removed the on_event hook; init now belongs in main.py's "
        "lifespan, not back on this router."
    )


def test_metrics_router_loaded_flag_true_on_successful_import(isolated_db):
    """Sanity check on the gating mechanism itself: a normal import (the
    metrics package is a real dependency here, not optional) must flip the
    flag main.py's lifespan checks before calling init_telemetry_schema."""
    import backend.main as main_module

    importlib.reload(main_module)
    assert main_module._metrics_router_loaded is True


def test_lifespan_initializes_telemetry_schema_before_first_request(isolated_db):
    """Direct regression lock for the actual migration: query the DuckDB
    file the isolated_db fixture points at, straight through the driver --
    not through a metrics.py endpoint -- to prove the app-level lifespan
    itself creates and seeds task_telemetry, with no HTTP request involved.
    This is the one on_event's removal could most plausibly have silently
    broken (e.g. if the new call were misplaced after the yield, or gated
    on the wrong flag)."""
    import backend.main as main_module
    from fastapi.testclient import TestClient

    importlib.reload(main_module)

    with TestClient(main_module.app):
        conn = duckdb.connect(isolated_db.DB_PATH)
        try:
            row_count = conn.execute("SELECT COUNT(*) FROM task_telemetry").fetchone()[0]
        finally:
            conn.close()

    assert row_count >= 5, (
        "task_telemetry has no seeded rows after the app's lifespan ran -- "
        "init_telemetry_schema() either didn't run or ran against the "
        "wrong DB path."
    )


def test_metrics_endpoints_still_work_end_to_end_through_real_client(client, make_auth_headers):
    """Not a duplicate of test_api_endpoints.py's RBAC coverage -- this
    confirms the full path (client fixture's own TestClient context ->
    lifespan -> init_telemetry_schema -> /api/v1/metrics/swarm reading
    task_telemetry) still works end-to-end after the on_event removal,
    using the same client/make_auth_headers fixtures every other endpoint
    test in this suite relies on."""
    headers = make_auth_headers("OPS09-METRICS-CLIENT", role="admin")
    resp = client.get("/api/v1/metrics/swarm", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
