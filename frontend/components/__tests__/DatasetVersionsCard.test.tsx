import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ClientProvider } from '../ClientContext';
import DatasetVersionsCard from '../DatasetVersionsCard';

// DATA-09 (versioning half): real component tests, mocking only
// global.fetch (the network boundary) -- rendered through a real
// ClientProvider so authToken/authReady/role come from the real context,
// same convention as SessionsCard.test.tsx.

function mockFetchOnce(response: { ok: boolean; status?: number; json?: () => Promise<any> }) {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: response.ok,
    status: response.status ?? (response.ok ? 200 : 500),
    json: response.json ?? (async () => ({})),
  });
}

async function renderSignedIn(role: string = 'owner') {
  window.sessionStorage.setItem('nexus_access_token', 'stored-token');
  window.sessionStorage.setItem('nexus_refresh_token', 'stored-refresh-token');
  mockFetchOnce({
    ok: true,
    json: async () => ({ user_id: 1, client_id: 'CLI-001', email: `${role}@test.example`, role }),
  }); // GET /api/v1/auth/me, from ClientProvider's own session restore

  const onDataChanged = jest.fn();
  render(
    <ClientProvider>
      <DatasetVersionsCard refreshTrigger={0} onDataChanged={onDataChanged} />
    </ClientProvider>
  );

  await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
  return { onDataChanged };
}

const TWO_VERSIONS = {
  versions: [
    { version_number: 2, archived_at: '2026-09-02T10:00:00', row_count: 5, replaced_by_filename: 'restore', source: 'RESTORE_SNAPSHOT' },
    { version_number: 1, archived_at: '2026-09-01T10:00:00', row_count: 3, replaced_by_filename: 'b.csv', source: 'REPLACED' },
  ],
};

beforeEach(() => {
  global.fetch = jest.fn();
  window.sessionStorage.clear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('DatasetVersionsCard', () => {
  it('loads and renders real dataset versions from GET /api/v1/data/dataset-versions', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: true, json: async () => TWO_VERSIONS });

    await waitFor(() => expect(screen.getByText('Version 2')).toBeInTheDocument());
    expect(screen.getByText('Version 1')).toBeInTheDocument();
    expect(screen.getAllByText(/superseded by/).length).toBeGreaterThan(0);
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/api/v1/data/dataset-versions'),
      expect.objectContaining({ headers: { Authorization: 'Bearer stored-token' } })
    );
  });

  it('shows a real empty state when there are no versions yet', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: true, json: async () => ({ versions: [] }) });

    await waitFor(() => expect(screen.getByText(/No dataset versions yet/)).toBeInTheDocument());
  });

  it('surfaces a real error when loading versions fails', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: false, status: 500, json: async () => ({}) });

    await waitFor(() => expect(screen.getByText('Server status: 500')).toBeInTheDocument());
  });

  it('clicking a version fetches and shows its real rows', async () => {
    await renderSignedIn();
    mockFetchOnce({ ok: true, json: async () => TWO_VERSIONS });
    await waitFor(() => expect(screen.getByText('Version 1')).toBeInTheDocument());

    mockFetchOnce({
      ok: true,
      json: async () => ({
        rows: [{ row_id: 1, date: '2026-01-01', category: 'Sales', amount: 100, description: 'Original row', is_recurring: null }],
      }),
    });
    fireEvent.click(screen.getByText('Version 1'));

    await waitFor(() => expect(screen.getByText(/Original row/)).toBeInTheDocument());
    expect(global.fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/api/v1/data/dataset-versions/1/rows'),
      expect.objectContaining({ headers: { Authorization: 'Bearer stored-token' } })
    );
  });

  it('does not show a Restore control for a member', async () => {
    await renderSignedIn('member');
    mockFetchOnce({ ok: true, json: async () => TWO_VERSIONS });
    await waitFor(() => expect(screen.getByText('Version 1')).toBeInTheDocument());

    expect(screen.queryByText('Restore')).not.toBeInTheDocument();
    expect(screen.getByText(/Only this tenant's owner or admin can restore/)).toBeInTheDocument();
  });

  it('an owner can restore a version after confirming, and the parent is notified', async () => {
    const { onDataChanged } = await renderSignedIn('owner');
    mockFetchOnce({ ok: true, json: async () => TWO_VERSIONS });
    await waitFor(() => expect(screen.getByText('Version 1')).toBeInTheDocument());

    const restoreButtons = screen.getAllByText('Restore');
    fireEvent.click(restoreButtons[1]); // Version 1's row
    expect(screen.getByText('Confirm restore')).toBeInTheDocument();

    mockFetchOnce({
      ok: true,
      json: async () => ({ status: 'SUCCESS', version_number: 1, rows_restored: 3, message: 'Restored dataset version 1 (3 row(s)).' }),
    }); // POST restore
    mockFetchOnce({ ok: true, json: async () => TWO_VERSIONS }); // reload after restore
    fireEvent.click(screen.getByText('Confirm restore'));

    await waitFor(() => expect(screen.getByText(/Restored dataset version 1/)).toBeInTheDocument());
    expect(onDataChanged).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/data/dataset-versions/1/restore'),
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('cancelling an armed restore makes no network call', async () => {
    await renderSignedIn('owner');
    mockFetchOnce({ ok: true, json: async () => TWO_VERSIONS });
    await waitFor(() => expect(screen.getByText('Version 1')).toBeInTheDocument());

    fireEvent.click(screen.getAllByText('Restore')[1]);
    expect(screen.getByText('Confirm restore')).toBeInTheDocument();

    const callsBeforeCancel = (global.fetch as jest.Mock).mock.calls.length;
    fireEvent.click(screen.getByText('Cancel'));

    expect(screen.queryByText('Confirm restore')).not.toBeInTheDocument();
    expect((global.fetch as jest.Mock).mock.calls.length).toBe(callsBeforeCancel);
  });

  it('surfaces the real backend error message when a restore fails', async () => {
    await renderSignedIn('owner');
    mockFetchOnce({ ok: true, json: async () => TWO_VERSIONS });
    await waitFor(() => expect(screen.getByText('Version 1')).toBeInTheDocument());

    fireEvent.click(screen.getAllByText('Restore')[1]);
    mockFetchOnce({ ok: false, status: 404, json: async () => ({ detail: 'Dataset version 1 does not exist for this tenant.' }) });
    fireEvent.click(screen.getByText('Confirm restore'));

    await waitFor(() => expect(screen.getByText('Dataset version 1 does not exist for this tenant.')).toBeInTheDocument());
  });
});
