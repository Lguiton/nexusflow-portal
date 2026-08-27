# Eivanta backend test suite

Real pytest tests against the actual backend code (not the stub-based
harness from an earlier session, which lived only in that session's
now-gone cloud sandbox and was never migrated here). Every test in this
suite either hits the real FastAPI app via `TestClient` or calls into
`db_manager.py` directly against an isolated, per-test DuckDB file — never
your real `backend/eivanta.duckdb`.

## Setup

From a Python 3.14 environment with the project's real dependencies
installed (see the root `venv/`, or create a fresh one and
`pip install -r backend/requirements.txt`):

```bash
pip install pytest pytest-asyncio
```

## Running

From the `eivanta-portal` project root, or from `backend/` — both work,
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
- `test_orchestrator_integration.py` — the LangGraph multi-agent router
  (`backend/agents/orchestrator.py`), previously exercised by NOTHING in
  this suite. Three layers: (1) `router_node`'s keyword dispatch table,
  every route plus the unmatched-query fallback to `virtual_cfo`, pure and
  deterministic; (2) `route_query()` through the real compiled graph
  against a real empty tenant, for several different routes, with zero
  network calls (every routed agent's own no-data guard returns before it
  would ever build an OpenAI client); (3) one real success-path test with
  real seeded ledger data where *only* the OpenAI network boundary is
  stubbed (same spy-client pattern as `tools/verify_byok_rollout.py`),
  proving the full router → graph node → real agent business logic → back
  through `route_query()`'s response-shaping wiring for a genuine success
  case too.
- `test_live_openai_agents_opt_in.py` — **opt-in, skipped by default.**
  The migrated, assertion-based replacement for four ad hoc root-level
  diagnostic scripts this repo used to carry (`test_agents.py`,
  `test_backbone.py`, `test_cfo_direct.py`, `test_db_manager_live.py`) —
  scripts with no `def test_*` functions that pytest never actually
  collected, meant to be run by hand and read by eye. `test_db_manager_
  live.py`'s checks are now fully superseded by `test_db_manager_queries.py`
  above and were not migrated; the other three scripts' unique value (real
  agent business logic against a real, currently-billed OpenAI call) is
  preserved here as real tests, gated behind
  `EIVANTA_RUN_LIVE_OPENAI_TESTS=1` plus a real `OPENAI_API_KEY` so a bare
  `pytest backend/tests` never spends money or needs a real key. See that
  file's own module docstring for exactly which old script each test
  replaces and why (including two real bugs those old scripts had — a
  nonexistent `code_customizer` import and a wrong keyword argument on
  `orchestrator.route_query` — that this migration fixed rather than
  carried forward).

## What's deliberately NOT covered here

Real LLM output from the 8 OpenAI-backed agents (virtual_cfo, bi_engineer,
predictive_forecaster, etc.) isn't exercised end-to-end in the DEFAULT
suite — that would mean a real, billed OpenAI API call per test run, with
non-deterministic output to assert against. What's tested by default
instead is that every such endpoint's auth gate runs before the agent is
ever invoked (`test_agent_endpoints_require_auth.py`), and that the full
orchestration pipeline is wired correctly with the OpenAI network boundary
stubbed (`test_orchestrator_integration.py`). Real, live-API coverage does
exist now, explicitly opt-in rather than mixed into the suite that runs on
every `pytest` invocation — see `test_live_openai_agents_opt_in.py` above.

Qdrant isn't tested either — as of this pass, nothing in `backend/` (agents,
routers, or `db_manager.py`) actually imports or calls a Qdrant client, so
there's no real integration point yet despite it being provisioned in
`docker-compose.yml`.
