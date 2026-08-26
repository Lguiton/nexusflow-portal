import { test, expect } from '@playwright/test';
import fs from 'fs';
import os from 'os';
import path from 'path';

// Real end-to-end coverage of the core dashboard flow: automatic dev-auth
// on load, the dashboard chrome rendering with real (not placeholder) data
// from an authenticated fetch, and a real CSV ledger upload through the
// live ETLDropzone -> FastAPI -> DuckDB path.
//
// These specs hit a REAL backend and a REAL, persistent DuckDB file (the
// same one `run-backend` uses in dev) under the default dev tenant
// (CLI-001 -- ClientContext's hardcoded default, see ClientContext.tsx).
// There's no per-test DB isolation here the way the pytest suite has via
// `isolated_db` -- that's a deliberate E2E tradeoff, not an oversight: a
// true end-to-end test needs to exercise the real dev-login -> real JWT ->
// real DuckDB write path, and standing this dashboard up against a
// throwaway DB per test isn't practical from Playwright's side. Practical
// consequence: assertions are written to hold regardless of what's already
// in CLI-001's ledger from prior manual testing or prior runs of this
// suite (see comments below on each assertion), and `workers: 1` /
// `fullyParallel: false` in playwright.config.ts keep these specs from
// racing each other over that shared state.
test.describe.serial('Eivanta dashboard core flow', () => {
  test('loads, authenticates automatically, and renders real (not placeholder) widget data', async ({ page }) => {
    await page.goto('/');

    // Header chrome renders regardless of backend state.
    await expect(page.getByRole('heading', { name: /Eivanta/i })).toBeVisible();

    // ClientProvider's dev-login effect must have completed successfully
    // against a real backend for this to ever show "Supervisor Online" --
    // health check needs the backend up.
    await expect(page.getByText('Supervisor Online')).toBeVisible({ timeout: 15000 });

    // Regression check for the documented SubAgentWidget bug (no
    // Authorization header -> permanent 401 -> permanent "-- / --"
    // placeholder). A real digit/digit pattern here means the widget's
    // authenticated fetch to /api/v1/metrics/swarm actually succeeded.
    await expect(page.getByText(/\d+\s*\/\s*\d+/).first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('-- / --')).toHaveCount(0);
  });

  test('uploads a CSV ledger through ETLDropzone and it succeeds instead of 401ing', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Supervisor Online')).toBeVisible({ timeout: 15000 });

    // Real CSV, written to a real temp file -- setInputFiles needs an
    // actual file on disk, not an in-memory blob.
    const csvPath = path.join(os.tmpdir(), `eivanta-e2e-${Date.now()}.csv`);
    const timestamp = Date.now();
    fs.writeFileSync(
      csvPath,
      [
        'date,category,amount,description',
        `2026-01-15,Revenue,1000,E2E test row ${timestamp}`,
      ].join('\n') + '\n',
      'utf-8'
    );

    try {
      const fileInput = page.locator('input[type="file"][accept=".csv"]');
      await fileInput.setInputFiles(csvPath);

      // Before the fix, this request 401'd and the raw backend error
      // string ("Missing or malformed Authorization header.") rendered
      // where "File Ingested Successfully!" now does -- this is the
      // direct regression check for that fix.
      await expect(page.getByText('File Ingested Successfully!')).toBeVisible({ timeout: 15000 });
      await expect(page.getByText('Upload Failed')).toHaveCount(0);

      // After ANY successful ingest, row_count for this tenant is
      // permanently > 0, so the "No ledger data yet" gap must be gone --
      // true regardless of what else was in CLI-001's ledger before this
      // test ran, so this holds up whether this is a fresh DB or one
      // that's already seen manual testing.
      await expect(page.getByText('No ledger data yet')).toHaveCount(0, { timeout: 15000 });
    } finally {
      fs.rmSync(csvPath, { force: true });
    }
  });
});
