import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ClientProvider } from '../ClientContext';
import KnownGapsPanel from '../KnownGapsPanel';

function renderWithProvider(ui: React.ReactElement) {
  return render(<ClientProvider>{ui}</ClientProvider>);
}

function mockFetch({ gapsOk, gaps }: { gapsOk: boolean; gaps?: any[] }) {
  (global.fetch as jest.Mock).mockImplementation((url: string) => {
    if (url.includes('/api/v1/auth/dev-login')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ access_token: 'test-token', client_id: 'CLI-001' }),
      });
    }
    if (url.includes('/api/v1/insights/known-gaps')) {
      if (!gapsOk) {
        return Promise.resolve({ ok: false, status: 502, json: async () => ({}) });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ client_id: 'CLI-001', row_count: 0, gaps: gaps ?? [] }),
      });
    }
    return Promise.reject(new Error(`Unexpected fetch to ${url}`));
  });
}

beforeEach(() => {
  global.fetch = jest.fn();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('KnownGapsPanel', () => {
  it('renders real gap entries once the backend responds', async () => {
    mockFetch({
      gapsOk: true,
      gaps: [
        { key: 'no_data', title: 'No ledger data yet', detail: 'Upload a CSV ledger to unlock everything.' },
      ],
    });

    renderWithProvider(<KnownGapsPanel />);

    await waitFor(() => expect(screen.getByText('No ledger data yet')).toBeInTheDocument());
    expect(screen.getByText('Upload a CSV ledger to unlock everything.')).toBeInTheDocument();
  });

  it('shows a real empty-state message when there are no gaps, not a spinner forever', async () => {
    mockFetch({ gapsOk: true, gaps: [] });

    renderWithProvider(<KnownGapsPanel />);

    await waitFor(() => expect(screen.getByText(/no known gaps/i)).toBeInTheDocument());
  });

  it('shows a translated error message, never a raw fetch/status error, when the request fails', async () => {
    mockFetch({ gapsOk: false });

    renderWithProvider(<KnownGapsPanel />);

    await waitFor(() => expect(screen.getByText('Unable to load known limitations right now.')).toBeInTheDocument());
    expect(screen.queryByText(/502/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Failed to fetch/i)).not.toBeInTheDocument();
  });
});
