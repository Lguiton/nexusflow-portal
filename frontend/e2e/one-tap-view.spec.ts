import { test, expect } from '@playwright/test';

// Real end-to-end coverage of Task 58 (UX-06)'s "One-Tap Insights" view --
// previously the only feature added since dashboard-core-flow.spec.ts was
// written that had zero E2E coverage. Same real-backend, real-DuckDB,
// shared-CLI-001-tenant tradeoff as dashboard-core-flow.spec.ts (see that
// file's own comment and e2e/README.md) -- assertions here are written to
// hold regardless of what's already in CLI-001's ledger, never asserting an
// exact number.
test.describe.serial('Eivanta One-Tap Insights view', () => {
  test('navigates to One-Tap Insights and all six buttons render', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Supervisor Online')).toBeVisible({ timeout: 15000 });

    await page.getByRole('button', { name: 'One-Tap Insights' }).click();

    for (const label of [
      "How's my business doing?",
      "What's coming next month?",
      'Show me my numbers',
      'Scan my expenses for red flags',
      'What should I do next?',
      'Generate a report I can share',
    ]) {
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }
  });

  test('tapping "Show me my numbers" expands the card and renders a real authenticated result, not a 401', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Supervisor Online')).toBeVisible({ timeout: 15000 });
    await page.getByRole('button', { name: 'One-Tap Insights' }).click();

    await page.getByText('Show me my numbers', { exact: true }).click();

    // Regression check for the same class of bug documented elsewhere in
    // this suite (SubAgentWidget/ETLDropzone): a missing Authorization
    // header on this POST would surface as a raw "Request failed: 401"
    // string in this exact spot. A real dollar figure means the
    // authenticated request to /api/v1/finance/analytics-summary actually
    // succeeded.
    await expect(page.getByText(/^\$[\d,]+$/).first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('Request failed: 401')).toHaveCount(0);
    await expect(page.getByText('Monthly AI usage cap reached.')).toHaveCount(0);

    // Tapping the same card again collapses it -- its content leaves the
    // page rather than just visually hiding, since OneTapView only renders
    // the expanded body when this card is the open one.
    await page.getByText('Show me my numbers', { exact: true }).click();
    await expect(page.getByText('View full analytics')).toHaveCount(0);
  });

  test('"View full analytics" navigates to the Analytics view', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Supervisor Online')).toBeVisible({ timeout: 15000 });
    await page.getByRole('button', { name: 'One-Tap Insights' }).click();
    await page.getByText('Show me my numbers', { exact: true }).click();

    await page.getByText('View full analytics').click();

    // The Analytics view's own real chrome -- confirms this actually
    // switched views rather than just being a dead link.
    await expect(page.getByRole('heading', { name: /Analytics/i })).toBeVisible({ timeout: 10000 });
  });
});
