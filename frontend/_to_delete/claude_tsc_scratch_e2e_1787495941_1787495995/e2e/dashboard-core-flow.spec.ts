import { test, expect } from '@playwright/test';
import fs from 'fs';
import os from 'os';
import path from 'path';

test.describe.serial('NexusFlow dashboard core flow', () => {
  test('loads, authenticates automatically, and renders real (not placeholder) widget data', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('heading', { name: /NexusFlow Analytics/i })).toBeVisible();
    await expect(page.getByText('Supervisor Online')).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(/\d+\s*\/\s*\d+/).first()).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('-- / --')).toHaveCount(0);
  });

  test('uploads a CSV ledger through ETLDropzone and it succeeds instead of 401ing', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Supervisor Online')).toBeVisible({ timeout: 15000 });

    const csvPath = path.join(os.tmpdir(), `nexusflow-e2e-${Date.now()}.csv`);
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

      await expect(page.getByText('File Ingested Successfully!')).toBeVisible({ timeout: 15000 });
      await expect(page.getByText('Upload Failed')).toHaveCount(0);
      await expect(page.getByText('No ledger data yet')).toHaveCount(0, { timeout: 15000 });
    } finally {
      fs.rmSync(csvPath, { force: true });
    }
  });
});
