import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ClientProvider, useClientId } from '../ClientContext';

// RBAC-01: rewritten for the real login/signup/session-restore flow.
// ClientContext no longer auto-authenticates on mount (the old
// "dev-login" behaviour these tests used to cover) -- it now only
// validates an ALREADY-STORED token via GET /api/v1/auth/me, and
// otherwise settles straight to a real signed-out state with zero
// fetch calls. Real login()/signup() are exercised directly instead of
// inferred from a mount-time side effect.

function Consumer() {
  const { clientId, authToken, authReady, user, login, retryLogin } = useClientId() as any;
  return (
    <div>
      <span data-testid="client-id">{clientId}</span>
      <span data-testid="ready">{String(authReady)}</span>
      <span data-testid="token">{authToken ?? 'null'}</span>
      <span data-testid="email">{user?.email ?? 'null'}</span>
      <button onClick={() => login('owner@test.example', 'password123')}>login</button>
      <button onClick={() => retryLogin()}>retry</button>
    </div>
  );
}

function mockFetchOnce(response: { ok: boolean; status?: number; json?: () => Promise<any> }) {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: response.ok,
    status: response.status ?? (response.ok ? 200 : 500),
    json: response.json ?? (async () => ({})),
  });
}

const REAL_USER = {
  user_id: 1, client_id: 'CLI-001', email: 'owner@test.example', role: 'owner',
};

beforeEach(() => {
  global.fetch = jest.fn();
  window.sessionStorage.clear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('ClientProvider / useClientId', () => {
  it('starts not-ready, becomes ready with no user and no fetch call when there is no stored session', async () => {
    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );

    expect(screen.getByTestId('ready').textContent).toBe('false');

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('token').textContent).toBe('null');
    // No stored token -- there is nothing to validate, so this never
    // calls the backend at all (unlike the old always-dev-login mount).
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('restores a valid session via /api/v1/auth/me when a token is already stored', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'stored-token');
    mockFetchOnce({ ok: true, json: async () => REAL_USER });

    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('token').textContent).toBe('stored-token');
    expect(screen.getByTestId('email').textContent).toBe('owner@test.example');
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/auth/me'),
      expect.objectContaining({ headers: { Authorization: 'Bearer stored-token' } })
    );
  });

  it('clears a stored token and becomes ready with no user when the session check fails', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'stale-token');
    mockFetchOnce({ ok: false, status: 401 });

    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('token').textContent).toBe('null');
    expect(window.sessionStorage.getItem('nexus_access_token')).toBeNull();
  });

  it('login() authenticates against /api/v1/auth/login and stores the returned token', async () => {
    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    mockFetchOnce({ ok: true, json: async () => ({ access_token: 'fresh-token', ...REAL_USER }) });
    fireEvent.click(screen.getByText('login'));

    await waitFor(() => expect(screen.getByTestId('token').textContent).toBe('fresh-token'));
    expect(screen.getByTestId('email').textContent).toBe('owner@test.example');
    expect(window.sessionStorage.getItem('nexus_access_token')).toBe('fresh-token');
  });

  it('retryLogin() re-validates whatever token is currently stored', async () => {
    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(global.fetch).not.toHaveBeenCalled();

    // Simulate a token having been stored out-of-band (e.g. login() just
    // completed) and confirm retryLogin() picks it up on re-check.
    window.sessionStorage.setItem('nexus_access_token', 'retry-token');
    mockFetchOnce({ ok: true, json: async () => REAL_USER });
    fireEvent.click(screen.getByText('retry'));

    await waitFor(() => expect(screen.getByTestId('token').textContent).toBe('retry-token'));
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});
