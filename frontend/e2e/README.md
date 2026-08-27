# Eivanta E2E suite (Playwright)

Real browser, real Next.js dev server, real FastAPI backend, real DuckDB
file. Nothing here is mocked -- this is the layer above the Jest suite
(which mocks `fetch`/`WebSocket` at the network boundary) and the pytest
suite (which hits a real backend but an isolated per-test DB). E2E
deliberately gives up per-test DB isolation to get the one thing neither of
those can: proof that the real browser, talking to the real running
backend, actually completes the flow.

## Setup (already done this session)

`@playwright/test` was already installed in your `npm install --save-dev
... @playwright/test` run. One more one-time step Playwright needs, which
that install doesn't cover -- downloading the actual browser binary:

```bash
cd frontend
npx playwright install chromium
```

## Running

You need **both** real services up first -- this suite doesn't try to
auto-start either of them (see the comment in `playwright.config.ts` for
why: the backend's lifecycle is `run-backend`, entirely outside npm, so
there's no single command Playwright could spawn to bring up both sides).

```bash
# terminal 1
run-backend

# terminal 2
cd frontend
npm run dev
```

If the frontend doesn't come up on port 3000 (e.g. something else already
has it, the way port 3000 was taken in your last run and it fell back to
3001), point Playwright at the real port instead of editing the config:

```bash
PLAYWRIGHT_BASE_URL=http://localhost:3001 npx playwright test
```

Otherwise, from `frontend/`:

```bash
npx playwright test
```

Add `--headed` to watch it drive a real browser, or `--ui` for Playwright's
interactive runner.

## I could not run this suite myself -- same root cause as the Jest suite

Two independent blockers from my side, either one alone would be enough:

1. **Network isolation.** My device bridge into your project is a
   separate, isolated VM from your own machine -- it shares the mounted
   project folder, nothing else. It cannot reach `localhost:3000` or
   `localhost:8000` on your machine, so even a working Playwright install
   on my side couldn't hit your real running servers.
2. **The same I/O-speed ceiling that blocked Jest.** Playwright's own cold
   start (browser launch + first navigation) is at least as heavy as
   Jest's first transform pass, which already couldn't finish inside my
   45-second-per-call ceiling on this mounted drive.

I did write-verify these specs carefully against the real DOM structure
(`app/page.tsx`, `ETLDropzone.tsx` after today's fix, `SubAgentWidget.tsx`)
and they pass a real `tsc --noEmit`. Please run them in your own terminal
and paste back whatever comes out -- if anything fails, I'll fix it.

## What's covered

- **Dashboard loads and authenticates automatically** -- `ClientProvider`'s
  dev-login effect completes against a real backend, the health check
  succeeds ("Supervisor Online"), and `SubAgentWidget` shows a real
  `N / M` count instead of its `-- / --` placeholder. That last check is a
  direct end-to-end regression test for the documented "SubAgentWidget
  never sent an Authorization header, so it 401'd forever" bug -- this
  time through a live browser and a live backend, not a mock.
- **CSV upload through `ETLDropzone` succeeds instead of 401ing** -- writes
  a real temp CSV, drives the real (now-hidden) file input, and asserts
  `"File Ingested Successfully!"` appears and `"Upload Failed"` doesn't.
  This is the direct end-to-end regression test for today's `ETLDropzone`
  fix. It also asserts the `"No ledger data yet"` known-gap is gone
  afterward, proving `dashboardRefreshTrigger` really propagated the
  upload into `KnownGapsPanel`'s next fetch.
- **`one-tap-view.spec.ts` (added 2026-08-26)** -- Task 58 (UX-06), the
  only feature added since the two specs above that had zero E2E coverage:
  navigating to the "One-Tap Insights" view renders all six buttons;
  tapping "Show me my numbers" renders a real authenticated dollar figure
  (regression check for the same "no Authorization header -> 401" bug
  class as `SubAgentWidget`/`ETLDropzone`, this time on `OneTapView`'s own
  POST requests) and collapses cleanly on a second tap; and "View full
  analytics" really navigates to the Analytics view rather than being a
  dead link.

  Same real-backend/real-DuckDB/shared-CLI-001-tenant tradeoff as the two
  specs above (see "A real tradeoff worth knowing about" below) -- I
  write-verified this one the same way (traced every assertion against the
  real `AppShell.tsx`/`OneTapView.tsx` DOM structure, confirmed the nav
  button's accessible name and the Analytics view's real `<h1>`, passes a
  real `tsc --noEmit`) but have NOT run it end-to-end myself. Unlike the
  Jest suite (see `components/__tests__/README.md`), actually running this
  one for real would mean standing up a full real FastAPI backend *and* a
  full real Next.js dev server together in a disposable sandbox -- a much
  bigger lift than mirroring Jest's component-level renders, and out of
  scope for this pass. Please run it the same way as the other two specs
  and paste back what comes out.

## A real tradeoff worth knowing about, not hiding

Both specs run against **CLI-001**, the same tenant `ClientContext`
defaults to in your own dev session, in the same persistent DuckDB file
`run-backend` uses. There's no throwaway DB per test the way the pytest
suite has. That's why every assertion above is written to hold regardless
of what's already in CLI-001's ledger (a real `N / M` count rather than a
specific number; "no longer says no data" rather than an exact row count)
-- but it does mean running this suite adds real rows to your real dev
data every time, and running it in parallel with your own manual testing
against CLI-001 could make either one flaky. If you want a dedicated E2E
tenant instead of piggybacking on CLI-001, that needs a real way to choose
which tenant a session logs in as (`ClientContext` currently hardcodes
`'CLI-001'`) -- worth its own small, deliberate feature if you want it,
not something to bolt on quietly here.

## What's not covered

Only the one core flow described above. Widget-level rendering coverage
(charts, CFO briefing, forecast) is Jest's job, not E2E's -- adding more
E2E specs (e.g. WebSocket telemetry over a real connection, multi-tenant
isolation through two real browser contexts) is a reasonable next step if
you want deeper coverage here.
