import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ClientProvider, useClientId } from '../ClientContext';

function Consumer() {
  const { clientId, authToken, authReady, retryLogin } = useClientId() as any;
  return (
    <div>
      <span data-testid="client-id">{clientId}</span>
      <span data-testid="ready">{String(authReady)}</span>
      <span data-testid="token">{authToken ?? 'null'}</span>
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

beforeEach(() => {
  global.fetch = jest.fn();
  window.sessionStorage.clear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('ClientProvider / useClientId', () => {
  it('starts not-ready, becomes ready with a real token after a successful dev-login', async () => {
    mockFetchOnce({ ok: true, json: async () => ({ access_token: 'real-jwt-token', client_id: 'CLI-001' }) });

    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );

    expect(screen.getByTestId('ready').textContent).toBe('false');

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('token').textContent).toBe('real-jwt-token');
    expect(window.sessionStorage.getItem('nexus_access_token')).toBe('real-jwt-token');
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/auth/dev-login'),
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('becomes ready with a null token when dev-login fails, instead of hanging forever', async () => {
    mockFetchOnce({ ok: false, status: 500 });

    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('token').textContent).toBe('null');
  });

  it('retryLogin() triggers a fresh dev-login attempt', async () => {
    mockFetchOnce({ ok: false, status: 500 });

    render(
      <ClientProvider>
        <Consumer />
      </ClientProvider>
    );

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('token').textContent).toBe('null');
    expect(global.fetch).toHaveBeenCalledTimes(1);

    mockFetchOnce({ ok: true, json: async () => ({ access_token: 'second-attempt-token' }) });
    fireEvent.click(screen.getByText('retry'));

    await waitFor(() => expect(screen.getByTestId('token').textContent).toBe('second-attempt-token'));
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });
});
