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

function mockDevLogin(ok: boolean) {
  (global.fetch as jest.Mock).mockImplementation((url: string) => {
    if (url.includes('/api/v1/auth/dev-login')) {
      return ok
        ? Promise.resolve({ ok: true, json: async () => ({ access_token: 'test-token', client_id: 'CLI-001' }) })
        : Promise.resolve({ ok: false, status: 500, json: async () => ({}) });
    }
    return Promise.reject(new Error(`Unexpected fetch to ${url}`));
  });
}

beforeEach(() => {
  global.fetch = jest.fn();
  MockWebSocket.instances = [];
  (global as any).WebSocket = MockWebSocket;
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('SwarmLogStreamer', () => {
  it('shows a Retry Authentication button (not the old dead dev-token flow) when auth fails, and it re-triggers login', async () => {
    mockDevLogin(false);
    renderWithProvider(<SwarmLogStreamer />);

    await waitFor(() => expect(screen.getByText('Authentication Failed')).toBeInTheDocument());
    expect(screen.getByText('Unable to authenticate the telemetry stream.')).toBeInTheDocument();

    mockDevLogin(true);
    fireEvent.click(screen.getByText('Retry Authentication'));

    await waitFor(() => expect(screen.getByText(/Verified Tenant|Connecting/)).toBeInTheDocument());
  });

  it('connects over the correct two-segment WS route with a token, and shows Verified Tenant once open', async () => {
    mockDevLogin(true);
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
    mockDevLogin(true);
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
    mockDevLogin(true);
    renderWithProvider(<SwarmLogStreamer sessionId="test-session" />);

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.onclose?.({ code: 4008 });
    });

    await waitFor(() => expect(screen.getByText('Authentication Failed')).toBeInTheDocument());
  });
});
