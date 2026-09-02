# Eivanta Backend API Inventory

_API-01 (Versioned API inventory and schemas). Generated 2 Sep 2026 from the real, running FastAPI app's own `app.openapi()` schema and each route's actual `Depends(...)` declaration in source -- not hand-maintained prose that can silently drift from the code. Regenerate by re-running the extraction described at the bottom of this file whenever the API surface changes meaningfully; `backend/tests/test_api01_inventory.py` is the automated guard that catches drift in the two structural conventions this pass introduced (versioning, tagging) between manual refreshes of this document.

## At a glance

- **64 REST endpoints** across 9 source files (`main.py` plus 8 included routers), all served by one FastAPI app (`backend/main.py`).
- **62 of 64** are versioned under `/api/v1/`. The other 2 -- `POST /api/finance/upload-ledger` and `POST /api/search` -- predate this convention and are live, frontend-consumed paths today; renaming either is a breaking change that needs coordinated frontend/consumer updates, and is explicitly NOT done in this pass. See **Known exceptions** below.
- Every endpoint now carries an OpenAPI **tag** (added in this pass -- previously none did), grouping `/docs` and `/redoc` by domain instead of one flat 64-row list.
- **1 WebSocket route** (`/ws/swarm/{client_id}/{session_id}`) exists outside this inventory's REST/OpenAPI scope -- WebSocket routes aren't part of the OpenAPI 3.0 spec FastAPI generates, so they never appear in `/openapi.json` regardless of tagging. See **WebSocket routes** below.
- **Machine-readable schema**: the full, always-current OpenAPI 3.0 document is served live at `GET /openapi.json` (interactive docs at `GET /docs`, `GET /redoc`) -- this file is a curated, grouped-by-domain companion to that, not a replacement for it.

## Known exceptions to the /api/v1/ convention

| Method | Path | Why it's grandfathered |
|---|---|---|
| POST | `/api/finance/upload-ledger` | Predates the `/api/v1/` convention; called by this exact path from `frontend/components/ETLDropzone.tsx`'s upload flow and covered by `backend/tests/test_sec03_sast_tmp_dir_hardening.py` and `backend/tests/test_ingestion_rate_limit.py`. |
| POST | `/api/search` | Predates the `/api/v1/` convention; the cognitive-search entry point (`secure_cognitive_search` in `backend/main.py`), a live, frontend-consumed path today. |

Both are enumerated by name in `test_api01_inventory.py::KNOWN_UNVERSIONED_LEGACY_PATHS` so a *third* unversioned endpoint can never sneak in silently, and so that migrating either one to `/api/v1/` (a real, disclosed decision for someone to make, not made here) is a one-line removal from that list rather than a forgotten exception.

## WebSocket routes

| Path | Auth |
|---|---|
| `WS /ws/swarm/{client_id}/{session_id}` | Token passed as a query param (`?token=...`); the server verifies the token's own tenant matches the `{client_id}` in the path and rejects the handshake (WS code 4008) otherwise -- see WS-01 and the hijacking-guard test in `backend/tests/test_websocket_swarm.py`. |

## Endpoints by domain

### Health

| Method | Path | Requires |
|---|---|---|
| GET | `/api/v1/health` | None (public) |

### Auth

| Method | Path | Requires |
|---|---|---|
| POST | `/api/v1/auth/login` | None (public) |
| POST | `/api/v1/auth/logout` | None (public) |
| GET | `/api/v1/auth/me` | Any authenticated member (works even while tenant is suspended) |
| POST | `/api/v1/auth/mfa/disable` | Any authenticated tenant member |
| POST | `/api/v1/auth/mfa/enable` | Any authenticated tenant member |
| POST | `/api/v1/auth/mfa/setup` | Any authenticated tenant member |
| GET | `/api/v1/auth/mfa/status` | Any authenticated tenant member |
| POST | `/api/v1/auth/mfa/verify` | Short-lived MFA challenge token (issued mid-login, not a full session) |
| POST | `/api/v1/auth/refresh` | None (public) |
| GET | `/api/v1/auth/sessions` | Any authenticated tenant member |
| POST | `/api/v1/auth/sessions/revoke-all` | Any authenticated tenant member |
| DELETE | `/api/v1/auth/sessions/{session_id}` | Any authenticated tenant member |
| POST | `/api/v1/auth/signup` | None (public) |

### Tenant & Team

| Method | Path | Requires |
|---|---|---|
| POST | `/api/v1/team/invite` | owner / admin |
| GET | `/api/v1/team/users` | Any authenticated tenant member |
| DELETE | `/api/v1/team/users/{target_user_id}` | owner only |
| PATCH | `/api/v1/team/users/{target_user_id}/role` | owner only |
| DELETE | `/api/v1/tenant` | owner only (works even while tenant is suspended) |
| GET | `/api/v1/tenant/export` | owner / admin (works even while tenant is suspended) |
| POST | `/api/v1/tenant/reactivate` | owner only (works even while tenant is suspended) |
| GET | `/api/v1/tenant/status` | Any authenticated member (works even while tenant is suspended) |
| POST | `/api/v1/tenant/suspend` | owner only (works even while tenant is suspended) |

### Ledger & Ingestion

| Method | Path | Requires |
|---|---|---|
| POST | `/api/finance/upload-ledger` | owner / admin / member |
| POST | `/api/v1/data/apply-category-suggestion` | owner / admin / member |
| POST | `/api/v1/data/category-suggestions` | Any authenticated tenant member |
| GET | `/api/v1/data/ingestion-history` | Any authenticated tenant member |
| POST | `/api/v1/data/schema-audit` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |
| DELETE | `/api/v1/finance/ledger` | owner / admin |
| POST | `/api/v1/finance/ledger-rows` | Any authenticated tenant member |

### BI & Analytics

| Method | Path | Requires |
|---|---|---|
| POST | `/api/v1/bi/chart-suite` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |
| POST | `/api/v1/bi/summary` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |
| POST | `/api/v1/finance/analytics-summary` | Any authenticated tenant member |
| POST | `/api/v1/finance/cfo-briefing` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |
| POST | `/api/v1/finance/comptroller-audit` | Any authenticated tenant member |
| POST | `/api/v1/finance/kpi-summary` | Any authenticated tenant member |

### Predictive & Forecasting

| Method | Path | Requires |
|---|---|---|
| GET | `/api/v1/finance/forecast-accuracy` | Any authenticated tenant member |
| POST | `/api/v1/predictive/forecast` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |
| POST | `/api/v1/predictive/scenario` | Any authenticated tenant member |

### SaaS Strategy

| Method | Path | Requires |
|---|---|---|
| POST | `/api/v1/saas/strategy` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |

### Reports

| Method | Path | Requires |
|---|---|---|
| GET | `/api/v1/reports/export-history` | owner / admin |
| POST | `/api/v1/reports/stakeholder` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |
| GET | `/api/v1/reports/stakeholder/export` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |

### Knowledge Base

| Method | Path | Requires |
|---|---|---|
| GET | `/api/v1/knowledge/documents` | Any authenticated tenant member |
| DELETE | `/api/v1/knowledge/documents/{doc_id}` | owner / admin / member |
| POST | `/api/v1/knowledge/query` | Any authenticated tenant member |
| POST | `/api/v1/knowledge/upload` | owner / admin / member |

### Telemetry & Metrics

| Method | Path | Requires |
|---|---|---|
| GET | `/api/v1/metrics/ai-usage` | owner / admin |
| GET | `/api/v1/metrics/ingestion` | owner / admin |
| GET | `/api/v1/metrics/swarm` | owner / admin |
| POST | `/api/v1/telemetry/map-schema` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |

### Insights & Assumptions

| Method | Path | Requires |
|---|---|---|
| GET | `/api/v1/assumptions` | Any authenticated tenant member |
| POST | `/api/v1/insights/known-gaps` | Any authenticated tenant member |

### Audit & Compliance

| Method | Path | Requires |
|---|---|---|
| GET | `/api/v1/audit/lineage` | Any authenticated tenant member |

### Settings

| Method | Path | Requires |
|---|---|---|
| GET | `/api/v1/settings/api-keys` | owner / admin |
| POST | `/api/v1/settings/api-keys` | owner / admin |
| DELETE | `/api/v1/settings/api-keys/{key_id}` | owner / admin |
| DELETE | `/api/v1/settings/budget` | owner / admin |
| GET | `/api/v1/settings/budget` | Any authenticated tenant member |
| POST | `/api/v1/settings/budget` | owner / admin |
| DELETE | `/api/v1/settings/byok` | owner / admin |
| GET | `/api/v1/settings/byok` | Any authenticated tenant member |
| POST | `/api/v1/settings/byok` | owner / admin |

### Search

| Method | Path | Requires |
|---|---|---|
| POST | `/api/search` | Any authenticated tenant member, subject to the tenant's AI-spend budget cap |

## How this was generated

1. `app.openapi()` on the real, imported `backend.main.app` gives the authoritative path/method list and confirms every route's `tags` field (added in this pass).
2. Each route's real `Depends(...)` expression is read directly from source (`main.py` and each included router file) rather than inferred, so the **Requires** column reflects the actual dependency the request goes through, not a guess.
3. `backend/tests/test_api01_inventory.py` re-derives the versioning and tagging facts from the live schema on every test run, so this document going stale on those two specific points is a test failure, not a silent drift -- though the fuller table here (domains, the **Requires** column) is still a manual refresh when the API surface changes.
