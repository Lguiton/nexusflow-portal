import { defineConfig, devices } from '@playwright/test';

// Real end-to-end config -- drives the actual Next.js dashboard against a
// real running backend, not a mock. Deliberately does NOT try to auto-start
// either service via `webServer`: the backend (FastAPI + DuckDB) has its own
// separate lifecycle (`run-backend`) outside npm entirely, so there's no
// single command Playwright could spawn that would bring up both sides.
// Start both yourself first (see e2e/README.md), then run `npx playwright
// test`.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // these specs share one real tenant's data in one real DuckDB file -- see e2e/README.md
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
