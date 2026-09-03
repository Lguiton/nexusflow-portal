"""
QA-02: Security and authorization regression suite.

Scope of THIS suite (the authn/authz boundary layer specifically):

  1. Every real, registered endpoint in the app -- other than a short,
     explicit allowlist of genuinely public ones (signup, login, refresh,
     logout, health, and the OpenAPI/docs pages) -- rejects a request that
     carries no Authorization header with a real 401, before any business
     logic runs.
  2. Every endpoint gated by require_role()/require_role_allow_suspended()
     rejects a correctly-authenticated request from a role OUTSIDE its
     allowed set with a real 403, and lets a request from an ALLOWED role
     past the gate (i.e. does NOT 401/403 it -- whatever happens next is
     that endpoint's own business logic, not this suite's concern).
  3. A handful of endpoints that take a target id straight from the URL
     path (a teammate's user_id, an API key's key_id) cannot be used by an
     authenticated user on ANOTHER tenant's record, even when that id is
     known/guessed -- confirmed both by the response code and by checking
     the target tenant's own record is actually untouched afterward.

Deliberately NOT in scope here (each is its own, separately tracked MBL
item): OpenAI/Qdrant-backed business-logic correctness once past the auth
gate (QA-03), load/soak testing (QA-04), agent-dropout/chaos testing
(QA-05), or browser/accessibility testing (QA-06). This suite is the
authn/authz boundary, and only that boundary.

Design note -- why this introspects the REAL app instead of a hand-typed
endpoint list (contrast with test_agent_endpoints_require_auth.py's
`@pytest.mark.parametrize` literal list, which is fine for that file's
much narrower, agent-specific scope): a hand-maintained list of "every
protected endpoint" silently goes stale the moment someone adds a new
route and forgets to add a matching line here -- exactly the failure mode
a security regression suite exists to catch. Walking backend.main.app's
real route table at collection time means a newly added endpoint is
automatically included in test 1 above the moment it exists; the only way
it can dodge coverage is by being deliberately added to PUBLIC_ROUTES
below, which is a conscious, visible, reviewable decision, not a silent
gap. test_route_inventory_matches_last_audit (bottom of this file) pins
the exact counts this was written against, specifically so that if the
route table ever changes shape, this suite fails loudly and by name
rather than quietly under- or over-counting.
"""
import inspect

import pytest

# Plain, one-time import of the real app -- deliberately NOT going through
# the isolated_db/app/client fixture chain conftest.py defines for actually
# ISSUING requests (those exist to give each test its own throwaway
# DuckDB file). Route registration (which paths/methods/dependencies
# exist) happens once at backend.main import time and does not depend on
# which DuckDB file is later monkeypatched in -- so a plain module-level
# import is sufficient and safe for walking the route table itself. Every
# actual HTTP call below still goes through the real `client` fixture, on
# its own isolated database, same as every other test file in this suite.
import backend.main as _main_module


def _all_api_routes(app):
    """
    Flattens backend.main.app.routes into a plain list of APIRoute
    objects, recursing into however this FastAPI version represents an
    include_router()-mounted router (an `_IncludedRouter` wrapper whose
    real routes live on `.original_router.routes`, empirically confirmed
    against the installed fastapi version -- NOT the classic bare
    `APIRouter` list some older FastAPI versions expose directly on
    `app.routes`). Falls back to walking any other object that merely has
    a `.routes` attribute, so this keeps working across a FastAPI version
    bump that changes the wrapper type's name again.
    """
    out = []

    def walk(routes):
        for r in routes:
            type_name = type(r).__name__
            if type_name == "APIRoute":
                out.append(r)
            elif type_name == "_IncludedRouter":
                walk(r.original_router.routes)
            elif hasattr(r, "routes"):
                walk(r.routes)
    walk(app.routes)
    return out


def _extract_allowed_roles(dep_fn):
    """
    require_role(*roles) / require_role_allow_suspended(*roles) both
    return a closure literally named `_dependency` that closes over an
    `allowed_roles` free variable (see backend/auth.py). Recovers that
    tuple straight from the live closure cell rather than re-deriving it
    from source text, so this stays correct even if auth.py's own
    docstrings/comments drift from its code. Returns None for any
    dependency that isn't one of these two factories (no `allowed_roles`
    free variable at all).
    """
    code = dep_fn.__code__
    if "allowed_roles" not in code.co_freevars:
        return None
    idx = code.co_freevars.index("allowed_roles")
    return dep_fn.__closure__[idx].cell_contents


def _route_dependency_names(route):
    sig = inspect.signature(route.endpoint)
    names = []
    for _, param in sig.parameters.items():
        default = param.default
        if hasattr(default, "dependency"):
            names.append(getattr(default.dependency, "__name__", None))
    return names


def _route_allowed_roles(route):
    """None if this route has no require_role()-style gate at all."""
    sig = inspect.signature(route.endpoint)
    for _, param in sig.parameters.items():
        default = param.default
        if not hasattr(default, "dependency"):
            continue
        if getattr(default.dependency, "__name__", None) != "_dependency":
            continue
        roles = _extract_allowed_roles(default.dependency)
        if roles is not None:
            return roles
    return None


# Every path parameter this app's protected/role-gated routes ever declare,
# filled with a syntactically-valid but almost-certainly-nonexistent value
# so a request can be routed at all. Real per-endpoint cross-tenant checks
# (which use REAL ids belonging to a real other tenant, not these
# placeholders) live further down as their own explicit tests.
_PATH_PARAM_FILL = {
    "target_user_id": "999999",
    "key_id": "999999",
    "doc_id": "nonexistent-doc-id",
    "session_id": "999999",
}


def _fill_path(path: str) -> str:
    for name, value in _PATH_PARAM_FILL.items():
        path = path.replace("{" + name + "}", value)
    return path


# Genuinely public endpoints -- reachable with NO Authorization header by
# design, not by omission. Anything else this app serves must reject a
# no-auth request with 401 (test_every_non_public_route_rejects_missing_auth
# below enforces exactly that for literally everything NOT in this set).
PUBLIC_ROUTES = {
    ("POST", "/api/v1/auth/signup"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/health"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
}

# A minimal, valid-shaped request body/files for the handful of routes
# that need one to get PAST body validation and actually reach the auth/
# role dependency being tested -- same reasoning
# test_agent_endpoints_require_auth.py already relies on (a missing body
# on a route that doesn't strictly require one is fine; a route that DOES
# require one gets a real minimal payload here so a 422 never masks what
# this suite is actually checking).
_REQUEST_KWARGS = {
    ("PATCH", "/api/v1/team/users/{target_user_id}/role"): {"json": {"role": "member"}},
    ("POST", "/api/v1/team/invite"): {"json": {"email": "someone@example.com", "role": "member"}},
    ("DELETE", "/api/v1/tenant"): {"json": {"confirm_company_name": "does-not-match"}},
    ("POST", "/api/v1/data/apply-category-suggestion"): {"json": {"row_id": 1, "new_category": "Software"}},
    ("POST", "/api/v1/settings/byok"): {"json": {"openai_api_key": "sk-test-not-real"}},
    ("POST", "/api/v1/settings/budget"): {"json": {"monthly_cap_usd": 50.0}},
    ("POST", "/api/finance/upload-ledger"): {"files": {"file": ("t.csv", b"date,amount\n2026-01-01,10\n", "text/csv")}},
    ("POST", "/api/v1/knowledge/upload"): {"files": {"file": ("t.txt", b"hello world", "text/plain")}},
}


def _request_kwargs(method, path):
    return dict(_REQUEST_KWARGS.get((method, path), {}))


_ALL_ROUTES = _all_api_routes(_main_module.app)

# (method, path) for every route this app registers, deduplicated -- one
# FastAPI APIRoute per (path, method-set), so a route allowing several
# methods is expanded to one key per method.
_ALL_ROUTE_KEYS = sorted({
    (method, r.path)
    for r in _ALL_ROUTES
    for method in (r.methods or set()) - {"HEAD", "OPTIONS"}
})

_PROTECTED_ROUTE_KEYS = [k for k in _ALL_ROUTE_KEYS if k not in PUBLIC_ROUTES]

# (method, path, allowed_roles) for every require_role()/
# require_role_allow_suspended()-gated route -- built by asking each real
# route object for its own dependency closure, not by re-typing a second
# list that could silently drift from auth.py's actual decorators.
_ROLE_GATED_ROUTES = []
for _r in _ALL_ROUTES:
    for _method in (_r.methods or set()) - {"HEAD", "OPTIONS"}:
        _roles = _route_allowed_roles(_r)
        if _roles is not None:
            _ROLE_GATED_ROUTES.append((_method, _r.path, tuple(_roles)))

_ALL_ROLES = ("owner", "admin", "member", "viewer")


# ---------------------------------------------------------------------
# 1. Every non-public route rejects a request with no Authorization header
# ---------------------------------------------------------------------
@pytest.mark.parametrize("method,path", _PROTECTED_ROUTE_KEYS, ids=[f"{m} {p}" for m, p in _PROTECTED_ROUTE_KEYS])
def test_every_non_public_route_rejects_missing_auth(client, method, path):
    kwargs = _request_kwargs(method, path)
    resp = client.request(method, _fill_path(path), **kwargs)
    assert resp.status_code == 401, (
        f"{method} {path} is not in PUBLIC_ROUTES, so it must reject a request with "
        f"no Authorization header with 401 -- got {resp.status_code}: {resp.text[:200]}"
    )


# ---------------------------------------------------------------------
# 2a. Role-gated routes reject every role NOT in their allowed set
# ---------------------------------------------------------------------
_DISALLOWED_ROLE_CASES = [
    (method, path, allowed, role)
    for method, path, allowed in _ROLE_GATED_ROUTES
    for role in _ALL_ROLES
    if role not in allowed
]


@pytest.mark.parametrize(
    "method,path,allowed,role", _DISALLOWED_ROLE_CASES,
    ids=[f"{m} {p} as {role} (allowed={allowed})" for m, p, allowed, role in _DISALLOWED_ROLE_CASES],
)
def test_role_gated_routes_reject_disallowed_roles(client, make_auth_headers, method, path, allowed, role):
    headers = make_auth_headers("QA02-ROLE-TENANT", role=role)
    kwargs = _request_kwargs(method, path)
    resp = client.request(method, _fill_path(path), headers=headers, **kwargs)
    assert resp.status_code == 403, (
        f"{method} {path} allows only {allowed} -- a '{role}' should get 403, got "
        f"{resp.status_code}: {resp.text[:200]}"
    )


# ---------------------------------------------------------------------
# 2b. Role-gated routes let every ALLOWED role past the gate
# ---------------------------------------------------------------------
_ALLOWED_ROLE_CASES = [
    (method, path, role)
    for method, path, allowed in _ROLE_GATED_ROUTES
    for role in allowed
]


@pytest.mark.parametrize(
    "method,path,role", _ALLOWED_ROLE_CASES,
    ids=[f"{m} {p} as {role}" for m, p, role in _ALLOWED_ROLE_CASES],
)
def test_role_gated_routes_accept_allowed_roles(client, make_auth_headers, method, path, role):
    headers = make_auth_headers("QA02-ROLE-TENANT-OK", role=role)
    kwargs = _request_kwargs(method, path)
    resp = client.request(method, _fill_path(path), headers=headers, **kwargs)
    assert resp.status_code not in (401, 403), (
        f"{method} {path} allows role '{role}' -- it should never be turned away at the "
        f"auth/role gate, got {resp.status_code}: {resp.text[:200]}"
    )


# ---------------------------------------------------------------------
# 3. Cross-tenant isolation on id-in-path endpoints
# ---------------------------------------------------------------------
def test_cannot_change_another_tenants_teammates_role(client, make_auth_headers):
    """
    A PATCH to /api/v1/team/users/{target_user_id}/role scoped by a
    tenant-A owner's own JWT must never touch a REAL user_id that belongs
    to tenant B, even though target_user_id is just an integer an attacker
    could enumerate/guess. Expects 404 (db_manager.update_user_role's own
    WHERE user_id = ? AND client_id = ? already returns False for this --
    this test exists so that guarantee is pinned by a real HTTP-level
    assertion, not just trusted from reading the SQL).
    """
    owner_a = make_auth_headers("QA02-ISO-A", role="owner")
    owner_b = make_auth_headers("QA02-ISO-B", role="owner")
    member_b = make_auth_headers("QA02-ISO-B", role="member")

    roster_b = client.get("/api/v1/team/users", headers=owner_b).json()["users"]
    member_b_id = next(u["user_id"] for u in roster_b if u["role"] == "member")

    resp = client.patch(
        f"/api/v1/team/users/{member_b_id}/role", headers=owner_a, json={"role": "owner"},
    )
    assert resp.status_code == 404, f"Expected 404 cross-tenant, got {resp.status_code}: {resp.text[:200]}"

    # The target tenant's own roster must be completely unaffected.
    roster_b_after = client.get("/api/v1/team/users", headers=owner_b).json()["users"]
    still_member = next(u for u in roster_b_after if u["user_id"] == member_b_id)
    assert still_member["role"] == "member", "Cross-tenant PATCH must never actually change the other tenant's data."


def test_cannot_remove_another_tenants_teammate(client, make_auth_headers):
    """Same guarantee as above, for DELETE /api/v1/team/users/{target_user_id}."""
    owner_a = make_auth_headers("QA02-ISO-C", role="owner")
    owner_b = make_auth_headers("QA02-ISO-D", role="owner")
    member_b = make_auth_headers("QA02-ISO-D", role="member")

    roster_b = client.get("/api/v1/team/users", headers=owner_b).json()["users"]
    member_b_id = next(u["user_id"] for u in roster_b if u["role"] == "member")

    resp = client.delete(f"/api/v1/team/users/{member_b_id}", headers=owner_a)
    assert resp.status_code == 404, f"Expected 404 cross-tenant, got {resp.status_code}: {resp.text[:200]}"

    roster_b_after = client.get("/api/v1/team/users", headers=owner_b).json()["users"]
    assert any(u["user_id"] == member_b_id for u in roster_b_after), (
        "Cross-tenant DELETE must never actually remove the other tenant's teammate."
    )


def test_cannot_revoke_another_tenants_api_key(client, make_auth_headers):
    """
    DELETE /api/v1/settings/api-keys/{key_id} scoped by a tenant-A owner's
    JWT must never revoke a REAL key_id belonging to tenant B --
    db_manager.revoke_api_key's own docstring already claims this
    ("Scoped to client_id AND key_id together so one tenant can never
    revoke another tenant's key"); this test holds that claim to a real
    HTTP-level check rather than trusting the docstring.
    """
    owner_a = make_auth_headers("QA02-ISO-E", role="owner")
    owner_b = make_auth_headers("QA02-ISO-F", role="owner")

    created = client.post("/api/v1/settings/api-keys", headers=owner_b, json={"label": "tenant-b-key"})
    assert created.status_code == 200, f"Setup failed creating tenant B's key: {created.text[:200]}"
    key_id = created.json()["key_id"]

    resp = client.delete(f"/api/v1/settings/api-keys/{key_id}", headers=owner_a)
    assert resp.status_code == 404, f"Expected 404 cross-tenant, got {resp.status_code}: {resp.text[:200]}"

    keys_b_after = client.get("/api/v1/settings/api-keys", headers=owner_b).json()["api_keys"]
    revoked_key = next(k for k in keys_b_after if k["key_id"] == key_id)
    assert revoked_key["active"] is True, "Cross-tenant DELETE must never actually revoke the other tenant's key."


# ---------------------------------------------------------------------
# 4. Self-audit: pin the shape of the route table this suite was written
#    against, so a future route addition/removal/reclassification fails
#    loudly here instead of silently changing this suite's real coverage.
# ---------------------------------------------------------------------
def test_route_inventory_matches_last_audit():
    """
    If this fails after a deliberate route change: recount PUBLIC_ROUTES
    (is the new/changed route genuinely meant to be reachable with no
    token?), update the literal numbers below, and re-run the full suite
    -- don't just bump the numbers to whatever makes it pass without
    checking a route didn't silently lose its auth dependency.
    """
    assert len(_ALL_ROUTE_KEYS) == 64, (
        f"Expected 64 total (method, path) APIRoute-registered business routes (matches API-01's "
        f"documented inventory as of 3 Sep 2026 -- the framework's own /docs, /redoc, /openapi.json "
        f"and /docs/oauth2-redirect pages are plain Starlette Route objects, not APIRoute, and are "
        f"deliberately NOT counted here), found {len(_ALL_ROUTE_KEYS)}. A route was added or removed "
        f"-- see this test's own docstring before changing this number."
    )
    # PUBLIC_ROUTES intentionally lists 9 entries: the 5 real APIRoute business
    # endpoints meant to be reachable with no token (signup/login/refresh/
    # logout/health) PLUS the 4 framework meta-pages above, kept in the same
    # set defensively in case a future FastAPI version ever registers those
    # as real APIRoutes -- only the 5 actually intersect _ALL_ROUTE_KEYS today.
    assert len(PUBLIC_ROUTES) == 9, "PUBLIC_ROUTES itself changed size -- update this alongside the audit."
    assert len([k for k in PUBLIC_ROUTES if k in _ALL_ROUTE_KEYS]) == 5
    assert len(_PROTECTED_ROUTE_KEYS) == 59, (
        f"Expected 59 protected business routes (64 total - 5 genuinely public), found "
        f"{len(_PROTECTED_ROUTE_KEYS)}."
    )
    assert len(_ROLE_GATED_ROUTES) == 23, (
        f"Expected 23 require_role()/require_role_allow_suspended()-gated routes, found "
        f"{len(_ROLE_GATED_ROUTES)}."
    )
