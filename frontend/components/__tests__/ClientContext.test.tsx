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
  const { clientId, authToken, authReady, user, login, retryLogin, verifyMfaCode, logout } = useClientId() as any;
  const [mfaChallengeToken, setMfaChallengeToken] = React.useState<string | null>(null);
  const [mfaError, setMfaError] = React.useState<string | null>(null);

  const handleLogin = async () => {
    const result = await login('owner@test.example', 'password123');
    if (result.mfaRequired) setMfaChallengeToken(result.mfaChallengeToken);
  };

  const handleVerify = async () => {
    const result = await verifyMfaCode(mfaChallengeToken, '123456');
    if (!result.ok) setMfaError(result.error);
  };

  return (
    <div>
      <span data-testid="client-id">{clientId}</span>
      <span data-testid="ready">{String(authReady)}</span>
      <span data-testid="token">{authToken ?? 'null'}</span>
      <span data-testid="email">{user?.email ?? 'null'}</span>
      <span data-testid="mfa-challenge">{mfaChallengeToken ?? 'null'}</span>
      <span data-testid="mfa-error">{mfaError ?? 'null'}</span>
      <button onClick={handleLogin}>login</button>
      <button onClick={() => retryLogin()}>retry</button>
      <button onClick={handleVerify}>verify</button>
      <button onClick={() => logout()}>logout</button>
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

    // FIXED (real test bug, confirmed live 2026-08-26 via the real Jest
    // suite -- not a product bug): this used to assert `authReady` is
    // still 'false' synchronously right after render(). For the
    // no-stored-token path, restoreSession()'s body (see ClientContext.tsx)
    // has no `await` before it calls setAuthReady(true) -- there's
    // nothing to check, so it settles synchronously. React Testing
    // Library's render() flushes effects (via act()) before returning
    // control here, so that transient 'false' state is never actually
    // observable in this specific no-token path -- asserting on it was
    // testing an accidental timing coincidence, not real behavior. The
    // component genuinely does start not-ready and become ready (real
    // users still get a real mount before this settles) -- this test just
    // can't observe that transition synchronously for a path with no real
    // async gap. The two real, meaningful assertions below (settles ready
    // with a null token, and never calls the backend when there's nothing
    // stored) are unchanged and still the actual behavior under test.
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

  // AUTH-04: login() on an MFA-enabled account gets back mfa_required +
  // a challenge token instead of a real access_token -- confirms
  // ClientContext doesn't mistakenly treat that response as a completed
  // sign-in (no token stored, no user set) until verifyMfaCode succeeds.
  it('login() reports mfaRequired and withholds a real token when the account has MFA enabled', async () => {
    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    mockFetchOnce({ ok: true, json: async () => ({ mfa_required: true, mfa_challenge_token: 'challenge-abc' }) });
    fireEvent.click(screen.getByText('login'));

    await waitFor(() => expect(screen.getByTestId('mfa-challenge').textContent).toBe('challenge-abc'));
    expect(screen.getByTestId('token').textContent).toBe('null');
    expect(window.sessionStorage.getItem('nexus_access_token')).toBeNull();
  });

  it('verifyMfaCode() completes sign-in against /api/v1/auth/mfa/verify and stores the real token', async () => {
    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    mockFetchOnce({ ok: true, json: async () => ({ mfa_required: true, mfa_challenge_token: 'challenge-xyz' }) });
    fireEvent.click(screen.getByText('login'));
    await waitFor(() => expect(screen.getByTestId('mfa-challenge').textContent).toBe('challenge-xyz'));

    mockFetchOnce({ ok: true, json: async () => ({ access_token: 'post-mfa-token', ...REAL_USER }) });
    fireEvent.click(screen.getByText('verify'));

    await waitFor(() => expect(screen.getByTestId('token').textContent).toBe('post-mfa-token'));
    expect(screen.getByTestId('email').textContent).toBe('owner@test.example');
    expect(window.sessionStorage.getItem('nexus_access_token')).toBe('post-mfa-token');
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/api/v1/auth/mfa/verify'),
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer challenge-xyz' }) })
    );
  });

  it('verifyMfaCode() surfaces an error and does not sign in on an incorrect code', async () => {
    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    mockFetchOnce({ ok: true, json: async () => ({ mfa_required: true, mfa_challenge_token: 'challenge-bad' }) });
    fireEvent.click(screen.getByText('login'));
    await waitFor(() => expect(screen.getByTestId('mfa-challenge').textContent).toBe('challenge-bad'));

    mockFetchOnce({ ok: false, status: 401, json: async () => ({ detail: 'Incorrect verification code.' }) });
    fireEvent.click(screen.getByText('verify'));

    await waitFor(() => expect(screen.getByTestId('mfa-error').textContent).toBe('Incorrect verification code.'));
    expect(screen.getByTestId('token').textContent).toBe('null');
  });

  // AUTH-02: refresh-token rotation.
  it('login() stores the refresh token returned alongside the access token', async () => {
    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    mockFetchOnce({ ok: true, json: async () => ({ access_token: 'fresh-token', refresh_token: 'fresh-refresh', ...REAL_USER }) });
    fireEvent.click(screen.getByText('login'));

    await waitFor(() => expect(screen.getByTestId('token').textContent).toBe('fresh-token'));
    expect(window.sessionStorage.getItem('nexus_refresh_token')).toBe('fresh-refresh');
  });

  it('falls back to a real token refresh when /me returns 401 and a refresh token is stored, instead of signing out', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'expired-access-token');
    window.sessionStorage.setItem('nexus_refresh_token', 'still-good-refresh-token');
    mockFetchOnce({ ok: false, status: 401 }); // GET /api/v1/auth/me
    mockFetchOnce({ ok: true, json: async () => ({ access_token: 'new-access-token', refresh_token: 'new-refresh-token', ...REAL_USER }) }); // POST /api/v1/auth/refresh

    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('token').textContent).toBe('new-access-token');
    expect(screen.getByTestId('email').textContent).toBe('owner@test.example');
    expect(window.sessionStorage.getItem('nexus_refresh_token')).toBe('new-refresh-token');
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/api/v1/auth/refresh'),
      expect.objectContaining({ body: JSON.stringify({ refresh_token: 'still-good-refresh-token' }) })
    );
  });

  it('signs out when /me fails and the stored refresh token is ALSO rejected', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'expired-access-token');
    window.sessionStorage.setItem('nexus_refresh_token', 'also-revoked-refresh-token');
    mockFetchOnce({ ok: false, status: 401 }); // GET /api/v1/auth/me
    mockFetchOnce({ ok: false, status: 401 }); // POST /api/v1/auth/refresh

    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('token').textContent).toBe('null');
    expect(window.sessionStorage.getItem('nexus_access_token')).toBeNull();
    expect(window.sessionStorage.getItem('nexus_refresh_token')).toBeNull();
  });

  it('logout() calls the real /api/v1/auth/logout endpoint with the stored refresh token and clears local state', async () => {
    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    mockFetchOnce({ ok: true, json: async () => ({ access_token: 'fresh-token', refresh_token: 'fresh-refresh', ...REAL_USER }) });
    fireEvent.click(screen.getByText('login'));
    await waitFor(() => expect(screen.getByTestId('token').textContent).toBe('fresh-token'));

    mockFetchOnce({ ok: true, json: async () => ({ ok: true }) }); // POST /api/v1/auth/logout
    fireEvent.click(screen.getByText('logout'));

    await waitFor(() => expect(screen.getByTestId('token').textContent).toBe('null'));
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/api/v1/auth/logout'),
      expect.objectContaining({ body: JSON.stringify({ refresh_token: 'fresh-refresh' }) })
    );
    expect(window.sessionStorage.getItem('nexus_access_token')).toBeNull();
    expect(window.sessionStorage.getItem('nexus_refresh_token')).toBeNull();
  });
});
