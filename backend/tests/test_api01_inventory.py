"""
API-01: a real regression guard over the backend's REST API surface --
not a snapshot of the current endpoint list (which would need editing
every time a new endpoint ships, defeating the point), but two structural
invariants any *new* endpoint should satisfy:

  1. Its path is versioned under /api/v1/, unless it's one of the two
     pre-existing, disclosed exceptions below.
  2. It carries at least one OpenAPI tag, so /docs and /redoc stay
     organized by domain instead of becoming one flat list as the API
     grows.

Both are read straight from app.openapi()["paths"] -- the same schema
FastAPI actually serves at GET /openapi.json -- so this test fails the
moment a real endpoint violates either invariant, not just when someone
remembers to update a checklist.

Scope, stated plainly: this is NOT authorization/RBAC coverage (see
RBAC-02's own test section for that) and NOT a full schema/contract test
(response shapes, pagination, idempotency -- see API-02's own open
items). It only guards the two structural things this pass actually
touched: versioning and tagging.
"""
from backend.main import app

# Two endpoints that predate this pass's /api/v1/ convention and are
# genuinely live, frontend-consumed paths today (POST /api/finance/
# upload-ledger is called by this exact path from frontend/components/
# ETLDropzone.tsx and covered by tests/test_sec03_sast_tmp_dir_hardening.py;
# POST /api/search is the cognitive-search entry point, also a live
# frontend-consumed path). Renaming either is a breaking API change
# that needs coordinated frontend/consumer updates -- explicitly NOT
# decided or done in this pass. Listed here, by name, so a *third*
# unversioned endpoint can never sneak in silently: only these two are
# grandfathered, and the reason each is here is written down, not just
# assumed.
KNOWN_UNVERSIONED_LEGACY_PATHS = {
    "/api/finance/upload-ledger",
    "/api/search",
}


def _rest_operations(schema: dict):
    """Yields (method, path, operation) for every real HTTP operation in
    the schema -- skips HEAD/OPTIONS, which FastAPI adds automatically
    and were never explicitly declared by any route in this codebase."""
    for path, methods in schema.get("paths", {}).items():
        for method, operation in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            yield method.upper(), path, operation


def test_every_new_endpoint_is_versioned_under_api_v1():
    schema = app.openapi()
    unversioned = [
        (m, p) for m, p, _ in _rest_operations(schema)
        if not p.startswith("/api/v1/") and p not in KNOWN_UNVERSIONED_LEGACY_PATHS
    ]
    assert unversioned == [], (
        "Found endpoint(s) not under /api/v1/ and not in the disclosed "
        f"legacy-exception list: {unversioned}. Either add the /api/v1/ "
        "prefix, or -- if this is a deliberate, reviewed exception like "
        "the two legacy paths above -- add it to "
        "KNOWN_UNVERSIONED_LEGACY_PATHS with a comment explaining why."
    )


def test_every_endpoint_carries_at_least_one_openapi_tag():
    schema = app.openapi()
    untagged = [(m, p) for m, p, op in _rest_operations(schema) if not op.get("tags")]
    assert untagged == [], (
        f"Found endpoint(s) with no OpenAPI tag: {untagged}. Every route "
        "decorator should pass tags=[\"Some Domain\"] so /docs and /redoc "
        "stay grouped by domain -- see backend/main.py's other routes "
        "(or the relevant router file) for the existing tag taxonomy."
    )


def test_known_legacy_unversioned_paths_still_exist_and_are_still_legacy():
    """Guards the OTHER direction: if upload-ledger or search ever DO get
    migrated to /api/v1/, this test starts failing (can't find the old
    path anymore) as a deliberate prompt to remove it from the exception
    list above -- rather than the exception list silently outliving the
    thing it was excusing."""
    schema = app.openapi()
    live_paths = {p for _, p, _ in _rest_operations(schema)}
    still_present = KNOWN_UNVERSIONED_LEGACY_PATHS & live_paths
    assert still_present == KNOWN_UNVERSIONED_LEGACY_PATHS, (
        f"Expected legacy paths {KNOWN_UNVERSIONED_LEGACY_PATHS} to still "
        f"exist; only found {still_present}. If one was migrated to /api/v1/, "
        "remove it from KNOWN_UNVERSIONED_LEGACY_PATHS above -- this test's "
        "failure is the intended prompt to do that, not a bug."
    )


def test_total_rest_endpoint_count_is_reasonable():
    """A loose sanity floor/ceiling, not a strict snapshot -- catches the
    two failure modes a strict count would miss the difference between:
    an import silently failing and dropping a whole router's routes
    (see the docstring note in tests/conftest.py's `app` fixture about
    routers being registered once at import time), versus the normal,
    expected drift of the API growing one or two endpoints at a time."""
    schema = app.openapi()
    count = len(list(_rest_operations(schema)))
    assert 55 <= count <= 200, (
        f"Got {count} REST endpoints -- expected somewhere in [55, 200]. "
        "A number far below 55 usually means a router failed to import "
        "(check for a swallowed ImportError in main.py's router-loading "
        "try/except blocks); a number far above 200 is just this test's "
        "ceiling needing to be raised as the API legitimately grows."
    )
