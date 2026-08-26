# Eivanta frontend test suite (Jest + React Testing Library)

Real component tests, not a stub harness. Every test renders the actual
component through a real `ClientProvider` (so the dev-login flow, and
`SwarmLogStreamer`'s new `retryLogin`, are exercised for real) with
`global.fetch` mocked at the network boundary -- never mocking React
internals or the components themselves.

## Setup (already done this session)

```bash
cd frontend
npm install --save-dev jest @testing-library/react @testing-library/jest-dom jest-environment-jsdom @playwright/test
```

One thing I missed when I gave you that command earlier: also install
`@types/jest`, or `tsc`/`next build`'s own type-check step will flag
`describe`/`it`/`expect`/`jest` as unknown names in these test files (a
missing-types problem, not a real bug -- Jest supplies these globals at
runtime regardless):

```bash
npm install --save-dev @types/jest
```

## Running

```bash
cd frontend
npx jest
```

## I could not run this suite myself -- here's why

I write-verified these tests carefully (traced every assertion against
the actual component source, fixed a couple of real mistakes I caught in
review -- e.g. `log_forecast_snapshot_sync`'s no-op-in-a-running-loop
behavior on the backend side), and they pass a real `tsc --noEmit`
type-check. But I could not actually execute `npx jest` from my side:
every attempt -- even a single trivial `expect(1+1).toBe(2)` test with no
imports -- hung for 40+ seconds with zero output and had to be killed.
`--listTests` and `find`/`ls` over `node_modules` both worked, just
slowly (a plain `find -maxdepth 2` over `node_modules` took over 5
seconds), which points to the device bridge's mounted-drive I/O being too
slow for Jest's first cold transform pass to finish inside the ~45-second
ceiling each of my shell calls gets -- not a problem with the tests
themselves. Running `npx jest` directly in your own terminal (real local
disk, no bridge) should behave completely differently.

Please run it and let me know what comes back -- if anything fails, paste
me the output and I'll fix it.

## What's covered

- `ClientContext.test.tsx` -- the real dev-login flow: becomes ready with
  a real token on success, becomes ready with a null token (not stuck
  forever) on failure, and the new `retryLogin()` actually re-triggers a
  fresh login attempt.
- `KnownGapsPanel.test.tsx` -- real gap rendering, the real empty state,
  and a translated (never raw) error message on failure.
- `AssumptionLedger.test.tsx` -- real numeric assumptions formatted by
  unit (usd to `$50,000`, `% per month` to `5%/mo`) and methodology notes,
  plus the translated error state.
- `SwarmLogStreamer.test.tsx` -- the restored "Retry Authentication"
  button actually re-triggers login (regression check that it's wired to
  the real `ClientContext.retryLogin()`, not the old dead
  `/api/auth/dev-token` endpoint); the WS connection targets the correct
  `/ws/swarm/{client_id}/{session_id}?token=...` route (regression check
  for the exact bug that was fixed); a real incoming message renders; and
  a 4008 close code is treated as an auth failure, not silently retried.
- `SubAgentWidget.test.tsx` -- the real `Authorization` header is sent
  (regression check for the documented "always-401, always shows `--`"
  bug), and a failed request leaves the real `--` placeholder rather than
  fabricating a number.

## What's not covered

`CognitiveSearchBar`, `VirtualCFOWidget`, `DataEngineerWidget`, and the
chart-rendering components (`DynamicChartEngine`, `SwarmVisualizer`,
`DataVisualizationWidget`) aren't covered yet -- these are good next
candidates if more component coverage is wanted.
