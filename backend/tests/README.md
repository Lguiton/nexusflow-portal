# NexusFlow backend test suite

Real pytest tests against the actual backend code (not the stub-based
harness from an earlier session, which lived only in that session's
now-gone cloud sandbox and was never migrated here). Every test in this
suite either hits the real FastAPI app via `TestClient` or calls into
`db_manager.py` directly against an isolated, per-test DuckDB file — never
your real `backend/nexusflow.duckdb`.

## Setup

From a Python 3.14 environment with the project's real dependencies
installed (see the root `venv/`, or create a fresh one and
`pip install -r backend/requirements.txt`):

```bash
pip install pytest pytest-asyncio
```

## Running

From the `nexusflow-portal` project root, or from `backend/` — both work,
`tests/conftest.py` adds the project root to `sys.path` itself regardless
of current directory:

```bash
pytest backend/tests -v
```

## What's covered

- `test_ingestion.py` — `ingest_csv_to_db` / `_read_csv_or_raise`: valid
  ingestion, empty/header-only/ragged/duplicate-column files, the
  amount-column detection rules (amount / revenue+expense / cost /
  expense), `$`/`,`/parenthetical-negative parsing, the recurring-flag
  token parser, row/column caps, replace-not-append re-upload semantics,
  identical-re-upload detection, tenant isolation.
- `test_db_manager_queries.py` — MRR (FIN-01, including the
  available-vs-$0.00-vs-unavailable distinction), ledger row drill-down
  and its filters (DIFF-01), category suggestions and applying one
  (DIFF-06, including the cross-tenant-cannot-touch-another-tenant's-row
  case), ingestion history (DATA-08), tenant-scoped deletion (DATA-09),
  forecast accuracy backtesting (FIN-04) including the documented
  no-op-inside-a-running-loop behavior of `log_forecast_snapshot_sync`.
- `test_api_endpoints.py` — every endpoint that doesn't call an
  OpenAI-backed agent: auth enforcement (401 on missing/garbage token),
  upload → history → delete round trip, analytics summary, KPI summary,
  the assumption ledger (checked against the live agent module constants
  it's supposed to read, not hardcoded expected values), known-gaps,
  category suggestions end-to-end via HTTP, cross-tenant isolation at the
  API layer, and the security-headers middleware.
- `test_websocket_swarm.py` — `/ws/swarm/{client_id}/{session_id}`: missing
  token, invalid token, and token/path client_id mismatch all close with
  4008; a valid matching token connects and receives a real CONNECTED
  message.
- `test_model_registry.py` — `AGENT_MODELS` / `REGISTRY_CHANGELOG`
  (AI-04) consistency.
- `test_agent_endpoints_require_auth.py` — every OpenAI-backed endpoint
  (cognitive search, CFO briefing, forecast, BI summary, schema audit,
  SaaS strategy, chart suite, stakeholder report) rejects a request with
  no/invalid auth *before* ever reaching the agent call.

## What's deliberately NOT covered here

Real LLM output from the 8 OpenAI-backed agents (virtual_cfo, bi_engineer,
predictive_forecaster, etc.) isn't exercised end-to-end — that would mean
a real, billed OpenAI API call per test run, with non-deterministic output
to assert against. What's tested instead is that every such endpoint's
auth gate runs before the agent is ever invoked. If real end-to-end agent
testing is wanted later, it belongs in its own explicitly opt-in suite
(e.g. gated behind an env var), not mixed into the suite that runs on
every `pytest` invocation.

Qdrant isn't tested either — as of this pass, nothing in `backend/` (agents,
routers, or `db_manager.py`) actually imports or calls a Qdrant client, so
there's no real integration point yet despite it being provisioned in
`docker-compose.yml`.
