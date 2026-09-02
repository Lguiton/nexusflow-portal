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

  it('warns on a telemetry seq gap but still renders the message (non-fatal)', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
    mockSessionRestore(true);
    renderWithProvider(<SwarmLogStreamer sessionId="test-session" />);

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0];
    const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});

    act(() => {
      ws.onopen?.();
      ws.onmessage?.({ data: JSON.stringify({ agent: 'Supervisor', status: 'CONNECTED', message: 'hi', seq: 0 }) });
      // Gap: expected seq 1, got seq 2 -- e.g. a message lost in transit.
      ws.onmessage?.({ data: JSON.stringify({ agent: 'bi_engineer', status: 'RUNNING', message: 'step two', seq: 2 }) });
    });

    await waitFor(() => expect(screen.getByText('step two')).toBeInTheDocument());
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('seq gap'));
    warnSpy.mockRestore();
  });
});

describe('SwarmLogStreamer reconnect backoff and watchdog (WS-01)', () => {
  // Real timers get the component through ClientContext's async auth-check
  // fetch first (a Promise, unaffected by fake timers); fake timers are
  // enabled only afterward, for the setTimeout/setInterval-driven behavior
  // this describe block actually exercises.
  afterEach(() => {
    jest.useRealTimers();
  });

  it('grows the reconnect delay exponentially per failed attempt, and caps it', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
    mockSessionRestore(true);
    const randomSpy = jest.spyOn(Math, 'random').mockReturnValue(0.5); // neutralizes +/-20% jitter exactly
    renderWithProvider(<SwarmLogStreamer sessionId="test-session" />);

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    jest.useFakeTimers();

    const expectDelayThenReconnect = (fromIndex: number, delayMs: number) => {
      act(() => {
        // eslint-disable-next-line security/detect-object-injection -- fromIndex is a numeric literal supplied by this test's own call sites, never external input
        MockWebSocket.instances[fromIndex].onclose?.({ code: 1006 });
      });
      act(() => {
        jest.advanceTimersByTime(delayMs - 1);
      });
      expect(MockWebSocket.instances.length).toBe(fromIndex + 1); // not yet -- one ms short
      act(() => {
        jest.advanceTimersByTime(1);
      });
      expect(MockWebSocket.instances.length).toBe(fromIndex + 2); // reconnected right at delayMs
    };

    // None of these instances ever call onopen -- every failure is
    // therefore consecutive, so the delay keeps growing: 3000, 6000,
    // 12000, 24000, then capped at 30000 (48000 uncapped).
    expectDelayThenReconnect(0, 3000);
    expectDelayThenReconnect(1, 6000);
    expectDelayThenReconnect(2, 12000);
    expectDelayThenReconnect(3, 24000);
    expectDelayThenReconnect(4, 30000);

    randomSpy.mockRestore();
  });

  it('resets the reconnect delay back to the base after a successful open', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
    mockSessionRestore(true);
    const randomSpy = jest.spyOn(Math, 'random').mockReturnValue(0.5);
    renderWithProvider(<SwarmLogStreamer sessionId="test-session" />);

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    jest.useFakeTimers();

    // Two consecutive failures grow the delay to 6000ms for the next one.
    act(() => {
      MockWebSocket.instances[0].onclose?.({ code: 1006 });
    });
    act(() => {
      jest.advanceTimersByTime(3000);
    });
    expect(MockWebSocket.instances.length).toBe(2);

    // This time the connection actually opens successfully before failing
    // again -- that success must reset the backoff back to the base delay.
    act(() => {
      MockWebSocket.instances[1].onopen?.();
      MockWebSocket.instances[1].onclose?.({ code: 1006 });
    });
    act(() => {
      jest.advanceTimersByTime(2999);
    });
    expect(MockWebSocket.instances.length).toBe(2); // not yet at the base delay
    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(MockWebSocket.instances.length).toBe(3); // reconnected at exactly the base 3000ms, not 6000ms

    randomSpy.mockRestore();
  });

  it('forces a reconnect if no message (including a heartbeat) arrives within the watchdog timeout', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
    mockSessionRestore(true);
    renderWithProvider(<SwarmLogStreamer sessionId="test-session" />);

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0];
    jest.useFakeTimers();

    act(() => {
      ws.onopen?.();
    });

    // Just under 3x the 5s heartbeat interval (15000ms) -- must not have
    // given up yet.
    act(() => {
      jest.advanceTimersByTime(14999);
    });
    expect(ws.closed).toBe(false);

    // Cross the watchdog timeout, plus one check-interval tick so the
    // watchdog's own polling interval has a chance to notice.
    act(() => {
      jest.advanceTimersByTime(2000);
    });
    expect(ws.closed).toBe(true);
  });

  it('does not force a reconnect while real messages keep arriving before the watchdog timeout', async () => {
    window.sessionStorage.setItem('nexus_access_token', 'test-token');
    mockSessionRestore(true);
    renderWithProvider(<SwarmLogStreamer sessionId="test-session" />);

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0];
    jest.useFakeTimers();

    act(() => {
      ws.onopen?.();
    });

    // Three simulated heartbeats, each well inside the 15s watchdog
    // timeout, spanning well past what a single un-refreshed watchdog
    // window would have allowed.
    for (let i = 0; i < 3; i++) {
      act(() => {
        jest.advanceTimersByTime(5000);
        ws.onmessage?.({ data: JSON.stringify({ agent: 'OrchestratorAgent', status: 'HEARTBEAT', message: 'hb', seq: i }) });
      });
    }

    expect(ws.closed).toBe(false);
  });
});
