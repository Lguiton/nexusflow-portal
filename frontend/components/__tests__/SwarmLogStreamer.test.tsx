import React from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { ClientProvider } from '../ClientContext';
import SwarmLogStreamer from '../SwarmLogStreamer';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close() {
    this.closed = true;
  }
}

function renderWithProvider(ui: React.ReactElement) {
  return render(<ClientProvider>{ui}</ClientProvider>);
}

const REAL_USER = { user_id: 1, client_id: 'CLI-001', email: 'owner@test.example', role: 'owner' };

// RBAC-01: ClientContext only auto-authenticates via an ALREADY-STORED
// token (validated against /api/v1/auth/me), unlike the old dev-login
// flow this used to mock, which authenticated on every mount regardless.
// `ok` controls whether that stored token validates.
function mockSessionRestore(ok: boolean) {
  (global.fetch as jest.Mock).mockImplementation((url: string) => {
    if (url.includes('/api/v1/auth/me')) {
      return ok
        ? Promise.resolve({ ok: true, json: async () => REAL_USER })
        : Promise.resolve({ ok: false, status: 401, json: async () => ({}) });
    }
    return Promise.reject(new Error(`Unexpected fetch to ${url}`));
  });
}

beforeEach(() => {
  global.fetch = jest.fn();
  MockWebSocket.instances = [];
  (global as any).WebSocket = MockWebSocket;
  window.sessionStorage.clear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('SwarmLogStreamer', () => {
  it('shows a Retry Authentication button when signed out, and retryLogin() re-checks for a session', async () => {
    // No stored token at all -- ClientContext settles straight to
    // signed-out (authReady=true, authToken=null) with no fetch call,
    // which this widget correctly renders as "Authentication Failed".
    renderWithProvider(<SwarmLogStreamer />);

    await waitFor(() => expect(screen.getByText('Authentication Failed')).toBeInTheDocument());
    expect(screen.getByText('Unable to authenticate the telemetry stream.')).toBeInTheDocument();

    // Simulate a session having appeared out-of-band (e.g. the user just
    // signed in via AuthGate elsewhere in the app) and confirm the Retry
    // button's retryLogin() call picks it up.
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
    mockSessionRestore(true);
    fireEvent.click(screen.getByText('Retry Authentication'));

    await waitFor(() => expect(screen.getByText(/Verified Tenant|Connecting/)).toBeInTheDocument());
  });

  it('connects over the correct two-segment WS route with a token, and shows Verified Tenant once open', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
    mockSessionRestore(true);
    renderWithProvider(<SwarmLogStreamer sessionId="test-session" />);

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0];
    expect(ws.url).toContain('/ws/swarm/CLI-001/test-session');
    expect(ws.url).toContain('token=test-token');

    act(() => {
      ws.onopen?.();
    });

    await waitFor(() => expect(screen.getByText(/Verified Tenant: CLI-001/)).toBeInTheDocument());
  });

  it('renders an incoming telemetry message', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
    mockSessionRestore(true);
    renderWithProvider(<SwarmLogStreamer sessionId="test-session" />);

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.onopen?.();
      ws.onmessage?.({ data: JSON.stringify({ agent: 'Supervisor', status: 'CONNECTED', message: 'Established secure telemetry tunnel' }) });
    });

    await waitFor(() => expect(screen.getByText('Established secure telemetry tunnel')).toBeInTheDocument());
    expect(screen.getByText('[Supervisor]')).toBeInTheDocument();
  });

  it('treats WS close code 4008 as an auth failure, not a silent retry loop', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
    mockSessionRestore(true);
    renderWithProvider(<SwarmLogStreamer sessionId="test-session" />);

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.onclose?.({ code: 4008 });
    });

    await waitFor(() => expect(screen.getByText('Authentication Failed')).toBeInTheDocument());
  });
});
