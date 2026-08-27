import React from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { ClientProvider } from '../ClientContext';
import OneTapView from '../views/OneTapView';

// Task 58 (UX-06) regression coverage -- previously OneTapView.tsx had no
// test at all. Real ClientProvider (auth token sourced from sessionStorage,
// same pattern as SubAgentWidget.test.tsx), global.fetch mocked at the
// network boundary only.

function renderWithProvider(ui: React.ReactElement) {
  return render(<ClientProvider>{ui}</ClientProvider>);
}

/**
 * OneTapView reads `authToken` directly from ClientContext on every click --
 * it doesn't gate on `authReady` itself. ClientContext's own real
 * session-restore effect (a real `await fetch('/api/v1/auth/me')`) hasn't
 * necessarily resolved yet in the same tick `render()` returns, so a click
 * fired immediately after render can race it and go out with no
 * Authorization header -- a real, if narrow, race that only matters if a
 * user could physically click within milliseconds of first paint. Tests
 * that need to assert on the real, authenticated request wait for that
 * real restore to settle first via `act`, matching how an actual user
 * waits for the page before tapping anything.
 */
async function renderWithProviderAndSettledAuth(ui: React.ReactElement) {
  const utils = render(<ClientProvider>{ui}</ClientProvider>);
  // A single microtask isn't enough to drain the real chain here (fetch
  // -> await res.json() -> two more state updates) -- a macrotask flush
  // via setTimeout(0) lets all of it settle before the click below.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return utils;
}

function mockAuthMe() {
  return {
    ok: true,
    json: async () => ({ user_id: 1, client_id: 'CLI-001', email: 'owner@test.example', role: 'owner' }),
  };
}

describe('OneTapView', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders all six one-tap buttons', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/v1/auth/me')) return Promise.resolve(mockAuthMe());
      return Promise.reject(new Error(`Unexpected fetch to ${url}`));
    });

    renderWithProvider(<OneTapView />);

    for (const label of [
      "How's my business doing?",
      "What's coming next month?",
      'Show me my numbers',
      'Scan my expenses for red flags',
      'What should I do next?',
      'Generate a report I can share',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('tapping a button sends a real Authorization header to the correct endpoint and renders the result', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/v1/auth/me')) return Promise.resolve(mockAuthMe());
      if (url.includes('/api/v1/finance/analytics-summary')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            status: 'OK',
            total_revenue: 12000,
            total_expense: 4500,
            net_profit: 7500,
            trend_note: 'Revenue is up month over month.',
          }),
        });
      }
      return Promise.reject(new Error(`Unexpected fetch to ${url}`));
    });

    await renderWithProviderAndSettledAuth(<OneTapView />);
    fireEvent.click(screen.getByText('Show me my numbers'));

    await waitFor(() => expect(screen.getByText('$7,500')).toBeInTheDocument());

    const numbersCall = (global.fetch as jest.Mock).mock.calls.find(([url]: [string]) =>
      url.includes('/api/v1/finance/analytics-summary')
    );
    expect(numbersCall).toBeDefined();
    const [, opts] = numbersCall;
    expect(opts.method).toBe('POST');
    expect(opts.headers.Authorization).toBe('Bearer test-token');
  });

  it('clicking an open card again collapses it without a second fetch', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/v1/auth/me')) return Promise.resolve(mockAuthMe());
      if (url.includes('/api/v1/finance/analytics-summary')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'OK', total_revenue: 1, total_expense: 1, net_profit: 0 }),
        });
      }
      return Promise.reject(new Error(`Unexpected fetch to ${url}`));
    });

    await renderWithProviderAndSettledAuth(<OneTapView />);
    fireEvent.click(screen.getByText('Show me my numbers'));
    await waitFor(() =>
      expect(
        (global.fetch as jest.Mock).mock.calls.some(([url]: [string]) => url.includes('analytics-summary'))
      ).toBe(true)
    );
    const callsAfterOpen = (global.fetch as jest.Mock).mock.calls.length;

    // Collapse.
    fireEvent.click(screen.getByText('Show me my numbers'));
    // Re-expand -- per the component's own caching comment, a card that
    // already succeeded this session should not re-fetch.
    fireEvent.click(screen.getByText('Show me my numbers'));

    expect((global.fetch as jest.Mock).mock.calls.length).toBe(callsAfterOpen);
  });

  it('shows the real backend detail message on a 402 budget-gate response', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/v1/auth/me')) return Promise.resolve(mockAuthMe());
      if (url.includes('/api/v1/finance/cfo-briefing')) {
        return Promise.resolve({
          ok: false,
          status: 402,
          json: async () => ({ detail: 'Monthly AI usage cap reached for this tenant.' }),
        });
      }
      return Promise.reject(new Error(`Unexpected fetch to ${url}`));
    });

    await renderWithProviderAndSettledAuth(<OneTapView />);
    fireEvent.click(screen.getByText("How's my business doing?"));

    await waitFor(() =>
      expect(screen.getByText('Monthly AI usage cap reached for this tenant.')).toBeInTheDocument()
    );
  });

  it('shows a generic error message on a non-402 failure, never a raw status code alone', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/v1/auth/me')) return Promise.resolve(mockAuthMe());
      if (url.includes('/api/v1/saas/strategy')) {
        return Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
      }
      return Promise.reject(new Error(`Unexpected fetch to ${url}`));
    });

    await renderWithProviderAndSettledAuth(<OneTapView />);
    fireEvent.click(screen.getByText('What should I do next?'));

    await waitFor(() => expect(screen.getByText('Request failed: 500')).toBeInTheDocument());
  });

  it('the "View full analytics" link navigates to the linked view', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/v1/auth/me')) return Promise.resolve(mockAuthMe());
      if (url.includes('/api/v1/finance/analytics-summary')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'OK', total_revenue: 1, total_expense: 1, net_profit: 0 }),
        });
      }
      return Promise.reject(new Error(`Unexpected fetch to ${url}`));
    });

    const onNavigateToView = jest.fn();
    await renderWithProviderAndSettledAuth(<OneTapView onNavigateToView={onNavigateToView} />);
    fireEvent.click(screen.getByText('Show me my numbers'));
    await waitFor(() => expect(screen.getByText('View full analytics')).toBeInTheDocument());

    fireEvent.click(screen.getByText('View full analytics'));
    expect(onNavigateToView).toHaveBeenCalledWith('analytics');
  });
});
