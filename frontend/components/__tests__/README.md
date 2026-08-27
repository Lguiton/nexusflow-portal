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

## This suite HAS now actually been run for real (2026-08-26)

The note that used to be here said this suite was only ever
"write-verified," never executed, because the device bridge's mounted-drive
I/O was too slow for Jest's cold transform pass to finish inside a 45-second
shell-call ceiling. That's now resolved: the whole suite was mirrored into a
disposable cloud sandbox (fresh `npm install` of the real
`next`/`react`/`jest`/`@testing-library/*` versions from `package.json`, no
network-bridge I/O involved) and run there directly with `npx jest`.

Doing that surfaced THREE real bugs that a "looks right on paper" review had
missed, all fixed as part of this pass:

1. **`AssumptionLedger.tsx`** and **`KnownGapsPanel.tsx`** both had the exact
   same raw-error UI leak already fixed once before in the Live Swarm
   Telemetry panel: `setError(err.message || "<friendly text>")`.
   `err.message` is always set (from the `throw new Error(...)` a few lines
   above), so the friendly fallback was dead code -- every real failure
   showed the user a raw `"...request failed: 500"` / `"...failed: 502"`
   instead of the intended friendly message. Fixed in both files to always
   use the friendly message (the technical detail is still logged via
   `console.error`/`console.warn`, just never shown to the user).
2. **`ClientContext.test.tsx`**'s first test asserted `authReady` was still
   `'false'` synchronously right after `render()` for the no-stored-token
   path. That path has no real `await` before it calls `setAuthReady(true)`,
   so React Testing Library's `act()`-wrapped `render()` flushes straight
   past it -- the assertion was checking an unobservable timing coincidence,
   not real behavior. Fixed by removing that specific assertion; the real,
   meaningful checks (settles ready, token stays null, no fetch call is
   made) are unchanged and still pass.

All fixes are complete-sentence-commented in place with `FIXED (real ... bug,
confirmed live 2026-08-26 via the real Jest suite ...)` so the history is
visible in the diff, not just in this README.

## Running

```bash
cd frontend
npx jest
```

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
- `OneTapView.test.tsx` -- Task 58 (UX-06), previously untested: all six
  buttons render; tapping one sends a real `Authorization` header to the
  correct backend endpoint and renders a real result; re-tapping an
  already-open card collapses it without a second fetch, and a card that
  already succeeded this session doesn't re-fetch on re-expand either; a
  402 budget-gate response surfaces the real backend `detail` message; a
  non-402 failure shows the generic message (never a raw status code
  alone); and the "View full analytics" link calls the real navigation
  callback with the right view id.

## What's not covered

`CognitiveSearchBar`, `VirtualCFOWidget`, `DataEngineerWidget`, and the
chart-rendering components (`DynamicChartEngine`, `SwarmVisualizer`,
`DataVisualizationWidget`) aren't covered yet -- these are good next
candidates if more component coverage is wanted.
