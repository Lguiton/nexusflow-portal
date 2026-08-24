# Phase 5 (Testing & QA) -- Final Report

Scope, per the SaaS Lifecycle Executive Manual's Phase 5 gaps: migrate the
old stub-based test harness to real PyTest/Jest, add integration testing,
add E2E testing (Playwright/Cypress), add dependency/security scanning.
Everything below was built and verified this session; execution/pass
confirmation for anything needing a live process or network access is
explicitly handed off, not silently assumed.

## 1. Backend -- real PyTest suite

`backend/tests/` (7 files + `conftest.py` + `pytest.ini`): ingestion
(valid/malformed CSVs, amount parsing, row caps, re-upload/replace,
tenant isolation), financial calculations (MRR eligibility rules,
forecast-accuracy snapshots -- including a real bug I caught in my own
first draft and fixed, see `backend/tests/README.md`), category
suggestions, model registry, REST auth-gating across every protected
endpoint, WebSocket auth (missing/invalid/mismatched-tenant token, all
close with 4008), and deliberate non-coverage of live LLM calls (cost/
determinism) and Qdrant (nothing in `backend/` actually uses it yet).

Every test hits the real FastAPI app and a real isolated per-test DuckDB
file (`isolated_db` fixture, via `monkeypatch`) -- never mocks the thing
under test.

**Status: written, `py_compile`-clean, not executed by me.** I have no
working Python 3.14 + real dependencies reachable from either of my
sandboxes, and no network egress from either to fix that myself. Run with:

```bash
cd backend  # or repo root, per pytest.ini's testpaths
pip install pytest pytest-asyncio
pytest tests -v
```

## 2. Frontend -- real Jest/RTL suite

`frontend/components/__tests__/` (5 files) + `jest.config.js` +
`jest.setup.ts`: `ClientContext`'s real dev-login flow (success, failure,
`retryLogin`), `KnownGapsPanel` and `AssumptionLedger` (real rendering +
translated, never-raw error states), `SwarmLogStreamer` (hand-built
`WebSocket` mock -- correct WS route/token, incoming messages, 4008
handling, the restored Retry button), `SubAgentWidget` (regression test
for the documented "no Authorization header -> permanent 401 -> permanent
`--`" bug).

Real components rendered through a real `ClientProvider`; only
`global.fetch`/`global.WebSocket` mocked at the true network boundary.

**Status: written, passes real `tsc --noEmit`, not executed by me.** Every
attempt from my side -- even a trivial no-import test -- hung past my
45-second-per-call ceiling; diagnosed as the mounted drive's I/O being too
slow for Jest's cold transform pass, not a problem with the tests
themselves. Run with:

```bash
cd frontend
npm install --save-dev @types/jest  # one thing I missed mentioning earlier
npx jest
```

## 3. E2E -- real Playwright suite

`frontend/playwright.config.ts` + `frontend/e2e/dashboard-core-flow.spec.ts`
+ `frontend/e2e/README.md`: drives a real Chromium browser against your
real running dev server and real backend. Covers dashboard load + automatic
dev-auth + real (non-placeholder) widget data, and a real CSV upload
through `ETLDropzone` all the way into DuckDB, with an assertion that the
"No ledger data yet" known-gap clears afterward (proving the refresh
propagated end-to-end). Deliberately scoped to one flow -- see
`e2e/README.md` for the tradeoffs (shared dev DB, no per-test isolation)
and what's not covered.

**Status: written, passes real `tsc --noEmit`, not executed by me** -- same
I/O-ceiling issue as Jest, plus my device bridge can't reach your
`localhost` at all (separate, network-isolated VM). Needs both `run-backend`
and `npm run dev` up, then `npx playwright test` from `frontend/`.

## 4. Dependency / security scanning

- **npm audit: done**, clean -- 0 vulnerabilities across all 717 resolved
  frontend packages.
- **pip-audit: handed off** -- `backend/requirements.txt` has no version
  pins, and neither of my sandboxes has PyPI access; your venv does. Exact
  commands in `docs/NexusFlow_Phase5_Dependency_Security_Scan.md`.
- **SAST: not started, deliberately flagged rather than picked for you** --
  tool choice and how deep to wire it in is a real process decision, not
  something with one obviously-correct default the way the audits are.
  Suggested low-effort starting commands (`bandit`, `eslint`) are in that
  same doc.

## 5. Bonus fix found along the way: ETLDropzone raw-error leak + broken auth

While reading the real upload flow to write the Playwright spec, found
that `ETLDropzone.tsx` -- the actual, currently-used CSV upload widget --
sent a no-op `X-Client-ID` header instead of a real `Authorization:
Bearer` token (the backend only ever read the latter), so every real
upload 401'd and the raw backend error string rendered directly in the UI.
Same bug class as the original Live Swarm Telemetry QA finding that
started this session, just in a more consequential, currently-live piece
of functionality. Fixed using the same `useClientId()` pattern every other
widget already uses, verified via real `tsc --noEmit`, delivered and
committed. Full writeup already shared in chat.

## What's still open / not decided for you

- **Actually running all three suites and confirming green.** I've
  type/syntax-verified everything I can from where I sit, but "these tests
  pass" is not something I can currently certify myself -- please run them
  and send me the output, especially anything red.
- **CI wiring.** None of pytest/Jest/Playwright/npm audit are hooked into
  any CI/CD pipeline yet -- that's a reasonable next Phase 5/6 step but a
  real infra decision (which CI, gating rules, secrets handling), not
  something to quietly stand up here.
- **SAST tool/policy**, as above.
- **Jest/E2E coverage gaps**, listed candidly in each suite's own README --
  `CognitiveSearchBar`, `VirtualCFOWidget`, `DataEngineerWidget`, and the
  chart components aren't Jest-covered yet; E2E covers exactly one core
  flow.
- **RBAC, billing, and email remain untouched**, per the standing
  directive -- nothing in this Phase 5 work builds, redesigns, or advances
  any of them ahead of schedule.
