import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ClientProvider } from '../ClientContext';
import SubAgentWidget from '../SubAgentWidget';

function renderWithProvider(ui: React.ReactElement) {
  return render(<ClientProvider>{ui}</ClientProvider>);
}

describe('SubAgentWidget', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('sends a real Authorization header on the swarm metrics request (regression check for the documented 401 bug)', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string, opts: any) => {
      if (url.includes('/api/v1/auth/dev-login')) {
        return Promise.resolve({ ok: true, json: async () => ({ access_token: 'test-token' }) });
      }
      if (url.includes('/api/v1/metrics/swarm')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ registered_agents: 8, total_capacity: 13 }),
        });
      }
      return Promise.reject(new Error(`Unexpected fetch to ${url}`));
    });

    renderWithProvider(<SubAgentWidget />);

    await waitFor(() => expect(screen.getByText('8 / 13')).toBeInTheDocument());

    const swarmCall = (global.fetch as jest.Mock).mock.calls.find(([url]: [string]) =>
      url.includes('/api/v1/metrics/swarm')
    );
    expect(swarmCall).toBeDefined();
    const [, opts] = swarmCall;
    expect(opts.headers.Authorization).toBe('Bearer test-token');
  });

  it('stays at the real "--" placeholder (not a fabricated number) if the request fails', async () => {
    (global.fetch as jest.Mock).mockImplementation((url: string) => {
      if (url.includes('/api/v1/auth/dev-login')) {
        return Promise.resolve({ ok: true, json: async () => ({ access_token: 'test-token' }) });
      }
      return Promise.resolve({ ok: false, status: 401, json: async () => ({}) });
    });

    renderWithProvider(<SubAgentWidget />);

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(screen.getByText('-- / --')).toBeInTheDocument();
  });
});
