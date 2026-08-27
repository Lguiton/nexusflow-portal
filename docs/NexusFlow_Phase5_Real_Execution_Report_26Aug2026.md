# Phase 5 (Testing & QA) -- Real Execution Report (2026-08-26)

This session closed the gap flagged at the bottom of
`NexusFlow_Phase5_Final_Report.md`: "Actually running all three suites and
confirming green." Everything below was actually executed in a disposable
cloud sandbox this session -- not just written and type/syntax-checked.
Real bugs turned up in the process, listed with what was changed.

## 1. Backend -- real PyTest run

Set up a real Python venv, installed `backend/requirements.txt` plus
`pytest`/`pytest-asyncio`, and ran the full `backend/tests/` suite for
real against the real FastAPI app and real per-test isolated DuckDB
files.

**Real bugs found and fixed:**

- **`backend/routers/swarm.py` -- `status.WS_4008_POLICY_VIOLATION` doesn't
  exist.** `starlette.status` has no such attribute (custom WebSocket
  close codes 4000-4999 are app-defined, never library constants). Every
  WebSocket-auth test that expected a 4008 close failed with a real
  `AttributeError`. Fixed by defining a local `WS_4008_POLICY_VIOLATION =
  4008` constant instead of relying on a symbol that was never real.
- **A systemic bug across 6 agent modules: `DB_PATH` captured by value,
  not live.** `virtual_cfo.py`, `data_engineer.py`, `saas_strategist.py`,
  `bi_engineer.py`, `predictive_forecaster.py`, and `report_generator.py`
  all did `from backend.db_manager import DB_PATH`, which snapshots the
  value at first import. `conftest.py`'s `isolated_db` fixture
  monkeypatches `db_manager.DB_PATH` per test -- which silently had zero
  effect on any of these six modules once one of them had been imported
  once in the test process, because they were each holding their own
  frozen copy of whatever `DB_PATH` was at that first import. This
  surfaced as a real test-order-dependent failure (a new integration test
  passed alone, failed as part of the full suite) -- the exact kind of bug
  that survives code review because it only shows up when two different
  DB paths are actually exercised in the same process. Fixed all 6 files
  to import the module itself (`from backend import db_manager`) and
  reference `db_manager.DB_PATH` live at every call site. Confirmed via a
  full suite rerun, order-independent.
- **`backend/tests/test_model_registry.py` -- test too narrow.** One
  assertion required every changelog entry's model name to start with
  `"gpt-"`, which broke on a legitimate, already-in-place
  `text-embedding-3-small` entry (added for `app/core/rag.py`'s
  persistent vector RAG, dated 2026-08-26 -- not something I added).
  Broadened to a whitelist of valid prefixes.

**New real coverage added:** `backend/tests/test_orchestrator_integration.py`
-- routes every keyword category through the real router, a case-
insensitivity check, a first-match-wins-on-overlap check, three real
no-data-tenant responses, real conversation history persistence across
two calls, and one full success path with a seeded real ledger and the
OpenAI boundary stubbed (not mocked business logic -- only the actual
network call out).

**Result: full suite passes for real, 133 tests, order-independent.**

## 2. Frontend -- real Jest/RTL run

Installed the real `package.json` dev dependencies (Jest, RTL,
`@types/jest`) in a fresh sandbox and ran the full
`frontend/components/__tests__/` suite for real.

**Real bugs found and fixed:**

- **`AssumptionLedger.tsx` and `KnownGapsPanel.tsx` leaked raw backend
  error strings to the UI.** Both did
  `setError(err.message || "<friendly text>")` -- but `err.message` is
  always truthy (it's set a few lines above from `throw new Error(...)`),
  making the friendly fallback dead code. A real 500/502 from the backend
  rendered as the raw `"...request failed: 500"` string instead of the
  intended friendly message. Same bug class as the earlier-fixed Live
  Swarm Telemetry panel issue. Fixed both to set the friendly message
  unconditionally.
- **`ClientContext.test.tsx` asserted an unobservable synchronous timing
  state.** One test checked `ready === 'false'` immediately after
  `render()`, which is not reliably observable -- React Testing Library's
  `act()`-wrapped render flushes past a no-`await` effect body before the
  next line runs. Removed that specific assertion; the real
  `await waitFor(...)` assertions in the same test still cover the
  behavior that matters.

**New real coverage added:** `frontend/components/__tests__/OneTapView.test.tsx`
-- all six one-tap buttons render, tapping one sends a real
`Authorization: Bearer` header and renders the real response, a second
tap collapses the card without a second fetch, a real 402 budget-gate
message renders, a generic error renders on other failures, and "View
full analytics" navigates to the linked view.

**Result: full suite passes for real**, all components covered
(`ClientContext`, `KnownGapsPanel`, `AssumptionLedger`, `SwarmLogStreamer`,
`SubAgentWidget`, `OneTapView`).

## 3. E2E -- still not executed (unchanged status, disclosed honestly)

Added `frontend/e2e/one-tap-view.spec.ts` for Task 58 (UX-06)'s "One-Tap
Insights" view, the one feature added since the original two specs that
had zero E2E coverage. Write-verified against the real DOM structure,
passes a real `tsc --noEmit`.

**Not run end-to-end this session** -- unlike Jest, actually running this
would require a full real FastAPI backend *and* a full real Next.js dev
server up together in a disposable sandbox at the same time, which is a
materially bigger lift than mirroring Jest's component-level renders and
was assessed as out of scope for this pass. Please run
`npx playwright test` yourself per `frontend/e2e/README.md` and paste back
what comes out -- same ask as before, now narrowed to just this one file
since the underlying flow the other two specs cover hasn't changed.

## 4. Dependency / security scanning

### npm audit -- unchanged from the 2026-08-23 result
Still clean: 0 vulnerabilities across all 717 resolved frontend packages.
Worth re-running periodically since this is a point-in-time result.

### pip-audit -- run for real this session (previously handed off)
Ran against a clean venv with exactly `backend/requirements.txt`
installed:

```
Found 9 known vulnerabilities in 2 packages
Name       Version ID              Fix Versions
---------- ------- --------------- ------------
pip        24.0    (7 CVEs)        26.1.2 / 26.0 / 26.1 / 26.2
setuptools 79.0.1  PYSEC-2026-3447 83.0.0
```

**None of the 13 actual application dependencies in `requirements.txt`
(fastapi, uvicorn, langgraph, duckdb, pandas, numpy, scipy, openai,
PyJWT, python-dotenv, pydantic, httpx, python-multipart) have any known
vulnerability in their currently-resolved versions.** The only two
flagged packages are `pip` and `setuptools` themselves -- the venv
bootstrap tooling that `python -m venv` installs automatically, not
anything the app imports or ships. Low urgency, but a real, actionable
fix if you want it: `pip install --upgrade pip setuptools` inside your
venv (no code or `requirements.txt` change needed).

### SAST -- run for real this session with `bandit` (previously flagged as an open decision, not started)

```
bandit -r backend -x backend/tests,backend/tools
Run metrics: 0 High, 5 Medium, 23 Low across 7,078 lines scanned
```

Every finding was traced by hand rather than reported at face value:

**Medium (5) -- all traced, 3 real vs. 2 false positive:**

- `bi_engineer.py:142` (B608) -- **false positive.** Flags an f-string
  that happens to contain SQL keywords, but it's a system-prompt string
  for the LLM, never executed as SQL.
- `bi_engineer.py:307` (B608) -- **false positive.** The `SELECT` is
  assembled entirely from fixed, code-authored vocabulary dicts
  (`_METRIC_SQL`, `_GROUP_BY_SQL`, etc.) keyed by strings that already
  passed `_validate_intent`'s whitelist; every actual data value is bound
  via `?` parameters. I also manually traced the adjacent `ORDER BY`
  clause (same function, not separately flagged by bandit but the same
  risk class) -- `_validate_intent` restricts its column to
  `select ∪ group_by` (themselves already whitelisted) and its direction
  to `("ASC", "DESC")` before either ever reaches the SQL string, so
  that's safe too.
- `db_manager.py:541` (B608) -- **false positive.** The dynamic
  `UPDATE tenants SET {...}` fragment list is built only from fixed
  string literals (`"stripe_customer_id = ?"`, etc.) chosen by which
  optional argument was passed -- never from a column name or value that
  could be attacker-influenced. Every actual value is bound via `?`.
- `main.py:~205` and `main.py:~698` (B108, hardcoded `/tmp` dirs) --
  **real, low-severity finding.** `/tmp/eivanta_ingest` and
  `/tmp/eivanta_knowledge` are hardcoded shared temp directories. Real
  filenames are either `client_id`-prefixed or `uuid4`-randomized, and the
  current deployment model is single-tenant-per-process, so practical
  exploitability (a symlink pre-plant race by another local user) is low
  today -- but it's a legitimate best-practice gap. Worth switching to
  `tempfile.mkdtemp()` (or an app-configured secure temp root) at some
  point; not urgent, not touched this session since it's a real design
  choice rather than a bug I'd fix silently.

**Low (23) -- all traced, all false positive / defensible-by-design:**

- 10x `B101:assert_used` -- every one is in `backend/swarm_test.py`, a
  test-style script that lives outside `backend/tests/` (so my scan
  exclusion didn't catch it). `assert` in test code is expected; this is
  bandit flagging test code as if it were production code.
- 11x `B110:try_except_pass` -- 10 in `db_manager.py` are the identical
  pattern (`try: ROLLBACK except: pass` inside an outer `except` that's
  already logging the real error -- if the rollback itself fails there's
  nothing more useful to do than swallow it), 1 in `websocket_manager.py`
  is closing an already-stale WebSocket connection where a failure is
  expected and harmless. Reviewed each; none swallow anything that
  matters.
- 2x `B105:hardcoded_password_string` -- both are the literal
  `"token_type": "bearer"` in `accounts.py`'s token response -- a label,
  not a password. Bandit's heuristic just matches the word "bearer".

## What's still open / not decided for you

- **E2E still needs to be run by you** -- same ask as the original Phase 5
  report, now covering one additional spec.
- **The two `B108` hardcoded-tmp-dir findings** -- flagged above as real
  but low-urgency; your call on whether/when to harden them.
- **`setuptools`/`pip` bump** -- a one-line venv command whenever you want
  it; not a code change.
- **RBAC, billing, and email remain untouched**, per the standing
  directive.
