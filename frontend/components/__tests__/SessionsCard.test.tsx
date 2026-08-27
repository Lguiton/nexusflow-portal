import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ClientProvider } from '../ClientContext';
import SessionsCard from '../SessionsCard';

// AUTH-06: real component tests, mocking only global.fetch (the network
// boundary) -- rendered through a real ClientProvider so authToken/
// authReady come from the real context, same convention as every other
// test in this suite (see __tests__/README.md).

function mockFetchOnce(response: { ok: boolean; status?: number; json?: () => Promise<any> }) {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: response.ok,
    status: response.status ?? (response.ok ? 200 : 500),
    json: response.json ?? (async () => ({})),
  });
}

async function renderSignedIn() {
  window.sessionStorage.setItem('nexus_access_token', 'stored-token');
  // A real already-signed-in session always has its refresh token
  // sitting alongside the access token (both written together by
  // login/signup/mfa-verify) -- set here so a later sign-out-everywhere
  // test can exercise ClientContext.logout()'s real server-side revoke.
  window.sessionStorage.setItem('nexus_refresh_token', 'stored-refresh-token');
  mockFetchOnce({
    ok: true,
    json: async () => ({ user_id: 1, client_id: 'CLI-001', email: 'owner@test.example', role: 'owner' }),
  }); // GET /api/v1/auth/me, from ClientProvider's own session restore

  render(
    <ClientProvider>
      <SessionsCard />
    </ClientProvider>
  );

  // Let session restore settle before the card's own GET /sessions fires.
  await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
}

const TWO_SESSIONS = {
  sessions: [
    { session_id: 1, device_label: 'Chrome on Windows', session_started_at: '2026-08-20T12:00:00', last_active_at: '2026-08-27T09:00:00', expires_at: '2026-09-19T12:00:00' },
    { session_id: 2, device_label: 'Safari on iOS', session_started_at: '2026-08-25T08:30:00', last_active_at: '2026-08-27T08:30:00', expires_at: '2026-09-24T08:30:00' },
  ],
};

beforeEach(() => {
  global.fetch = jest.fn();
  window.sessionStorage.clear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('SessionsCard', () => {
  it('loads and renders the real active sessions from GET /api/v1/auth/sessions', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: true, json: async () => TWO_SESSIONS });

    await waitFor(() => expect(screen.getByText('Chrome on Windows')).toBeInTheDocument());
    expect(screen.getByText('Safari on iOS')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/api/v1/auth/sessions'),
      expect.objectContaining({ headers: { Authorization: 'Bearer stored-token' } })
    );
  });

  it('shows a real empty state when there are no active sessions', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: true, json: async () => ({ sessions: [] }) });

    await waitFor(() => expect(screen.getByText('No active sessions found.')).toBeInTheDocument());
  });

  it('surfaces a real error and an empty (never fabricated) list when loading sessions fails', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: false, status: 500, json: async () => ({}) });

    await waitFor(() => expect(screen.getByText('No active sessions found.')).toBeInTheDocument());
    expect(screen.getByText('Server status: 500')).toBeInTheDocument();
  });

  it('signing out one device calls DELETE on that session id and removes it from the list', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: true, json: async () => TWO_SESSIONS });
    await waitFor(() => expect(screen.getByText('Safari on iOS')).toBeInTheDocument());

    mockFetchOnce({ ok: true, json: async () => ({ session_id: 2, revoked: true }) });
    const signOutButtons = screen.getAllByText('Sign out');
    fireEvent.click(signOutButtons[1]);

    await waitFor(() => expect(screen.queryByText('Safari on iOS')).not.toBeInTheDocument());
    expect(screen.getByText('Chrome on Windows')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/api/v1/auth/sessions/2'),
      expect.objectContaining({ method: 'DELETE' })
    );
  });

  it('surfaces the real backend error message when signing out a device fails', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: true, json: async () => TWO_SESSIONS });
    await waitFor(() => expect(screen.getByText('Chrome on Windows')).toBeInTheDocument());

    mockFetchOnce({ ok: false, status: 404, json: async () => ({ detail: 'No matching active session found.' }) });
    fireEvent.click(screen.getAllByText('Sign out')[0]);

    await waitFor(() => expect(screen.getByText('No matching active session found.')).toBeInTheDocument());
    // The failed session is NOT optimistically removed.
    expect(screen.getByText('Chrome on Windows')).toBeInTheDocument();
  });

  it('sign-out-everywhere requires confirmation, then calls revoke-all and clears local auth state', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: true, json: async () => TWO_SESSIONS });
    await waitFor(() => expect(screen.getByText('Chrome on Windows')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Sign out of all devices'));
    expect(screen.getByText(/immediately signs out every device/i)).toBeInTheDocument();

    mockFetchOnce({ ok: true, json: async () => ({ ok: true }) }); // POST revoke-all
    mockFetchOnce({ ok: true, json: async () => ({ ok: true }) }); // POST /api/v1/auth/logout (from context logout())
    fireEvent.click(screen.getByText('Confirm sign out everywhere'));

    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/auth/sessions/revoke-all'),
        expect.objectContaining({ method: 'POST' })
      )
    );
    await waitFor(() => expect(window.sessionStorage.getItem('nexus_access_token')).toBeNull());
  });

  it('cancelling the sign-out-everywhere confirmation makes no network call', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: true, json: async () => TWO_SESSIONS });
    await waitFor(() => expect(screen.getByText('Chrome on Windows')).toBeInTheDocument());

    const callsBefore = (global.fetch as jest.Mock).mock.calls.length;
    fireEvent.click(screen.getByText('Sign out of all devices'));
    fireEvent.click(screen.getByText('Cancel'));

    expect(screen.queryByText(/immediately signs out every device/i)).not.toBeInTheDocument();
    expect((global.fetch as jest.Mock).mock.calls.length).toBe(callsBefore);
  });
});
