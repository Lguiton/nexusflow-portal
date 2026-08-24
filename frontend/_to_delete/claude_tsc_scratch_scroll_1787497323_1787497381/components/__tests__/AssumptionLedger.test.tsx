import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ClientProvider } from '../ClientContext';
import AssumptionLedger from '../AssumptionLedger';

function renderWithProvider(ui: React.ReactElement) {
  return render(<ClientProvider>{ui}</ClientProvider>);
}

function mockFetch(assumptionsResponse: any) {
  (global.fetch as jest.Mock).mockImplementation((url: string) => {
    if (url.includes('/api/v1/auth/dev-login')) {
      return Promise.resolve({ ok: true, json: async () => ({ access_token: 'test-token' }) });
    }
    if (url.includes('/api/v1/assumptions')) {
      return Promise.resolve({ ok: true, json: async () => assumptionsResponse });
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

describe('AssumptionLedger', () => {
  it('renders real numeric assumptions and methodology notes from the backend, formatted by unit', async () => {
    mockFetch({
      numeric_assumptions: [
        {
          key: 'assumed_cash_reserves', label: 'Assumed Cash Reserves', value: 50000, unit: 'usd',
          used_by: 'Virtual CFO -- Cash Runway', description: 'A placeholder reserve figure.',
        },
        {
          key: 'materially_declining_pct', label: 'Materiality Threshold for Decline', value: 5, unit: '% per month',
          used_by: 'Predictive Forecaster', description: 'Threshold description.',
        },
      ],
      methodology_notes: [
        { key: 'mrr_definition', label: 'MRR Definition', used_by: 'Finance KPIs', description: 'Transaction-based, not contract-based.' },
      ],
    });

    renderWithProvider(<AssumptionLedger />);

    await waitFor(() => expect(screen.getByText('Assumed Cash Reserves')).toBeInTheDocument());
    expect(screen.getByText('$50,000')).toBeInTheDocument();
    expect(screen.getByText('5%/mo')).toBeInTheDocument();
    expect(screen.getByText('MRR Definition')).toBeInTheDocument();
    expect(screen.getByText('Transaction-based, not contract-based.')).toBeInTheDocument();
  });

  it('shows a translated error message rather than a raw fetch failure', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/v1/auth/dev-login')) {
        return Promise.resolve({ ok: true, json: async () => ({ access_token: 'test-token' }) });
      }
      return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
    });

    renderWithProvider(<AssumptionLedger />);

    await waitFor(() => expect(screen.getByText('Assumption ledger is currently unavailable.')).toBeInTheDocument());
  });
});
