'use client';

import React, { useState } from 'react';
import { UploadCloud, CheckCircle, AlertCircle, Loader2, ShieldAlert } from 'lucide-react';
import { useClientId } from './ClientContext';

// Fixed 2026-08-23 -- this component previously kept its own disconnected
// local `clientId` state (a free-text "Simulate Client:" box, default
// 'AGENCY-123') and sent it as a custom `X-Client-ID` header. The real
// backend endpoint (/api/finance/upload-ledger) has only ever required
// `Depends(verify_jwt_and_get_client_id)`, which reads `Authorization:
// Bearer <jwt>` and ignores X-Client-ID entirely -- so that header did
// nothing, the "simulate a different tenant" box never worked, and every
// real upload through this component 401'd. The catch block then rendered
// `data.detail` (the raw backend error string, e.g. "Missing or malformed
// Authorization header.") straight into the UI -- the same class of bug
// as the original Live Swarm Telemetry QA finding, just in the live CSV
// ingestion flow instead.
//
// Fix: consume the same useClientId()/authToken/authReady wiring every
// other dashboard widget already uses, send a real Authorization header,
// and gate the dropzone on auth being ready -- mirroring
// SwarmLogStreamer's "Authentication Failed" / "Retry Authentication"
// treatment so the two surfaces behave consistently. The free-text
// tenant-simulator input is removed rather than reconnected: it never
// actually changed which tenant the upload landed in, so "fixing" it
// would mean wiring a second, independent client-switching mechanism next
// to the one ClientContext already owns. If a real multi-client switcher
// for local testing is wanted, that's a small separate feature to build
// deliberately (and flag), not something to reintroduce silently here.
export default function ETLDropzone({ onUploadSuccess }: { onUploadSuccess?: () => void }) {
  const { clientId, authToken, authReady, retryLogin } = useClientId();

  const [isHovering, setIsHovering] = useState(false);
  const [status, setStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleFileUpload = async (file: File) => {
    if (!authToken) {
      setStatus('error');
      setErrorMessage('Not authenticated yet -- please retry authentication below.');
      return;
    }

    setStatus('uploading');
    setErrorMessage(null);

    const formData = new FormData();
    formData.append('file', file);

    const apiUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000';

    try {
      const res = await fetch(`${apiUrl}/api/finance/upload-ledger`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${authToken}`,
        },
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        // Auth/authorization-layer failures (401/403) are infrastructure
        // detail, not user-facing feedback -- translate those rather than
        // showing the raw backend string, and point at the same recovery
        // path SwarmLogStreamer uses. Other 4xx (e.g. a malformed CSV) are
        // genuine, useful validation feedback about the file itself, so
        // those are still shown as returned.
        if (res.status === 401 || res.status === 403) {
          throw new Error('AUTH_FAILURE');
        }
        throw new Error(data.detail || 'Failed to upload ledger.');
      }

      setStatus('success');
      onUploadSuccess?.();
      setTimeout(() => setStatus('idle'), 4000);
    } catch (err: any) {
      console.error('Upload error:', err);
      setStatus('error');
      if (err.message === 'AUTH_FAILURE') {
        setErrorMessage('Your session needs to be re-authenticated before uploading.');
      } else {
        setErrorMessage(err.message || 'Network error connecting to FastAPI backend.');
      }
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsHovering(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const authBlocked = authReady && !authToken;

  return (
    <div className="w-full mt-6">
      <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-lg font-bold flex items-center gap-2 text-white">
            <UploadCloud className="text-cyan-400 w-5 h-5" />
            Automated Data Ingestion (DuckDB)
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Drop CSVs here to ingest structured financial logs into your live database.
          </p>
        </div>
      </div>

      {authBlocked ? (
        <div className="w-full border-2 border-dashed border-red-900/60 bg-red-950/20 rounded-xl flex flex-col items-center justify-center gap-3 p-6 text-red-300">
          <ShieldAlert className="w-8 h-8 text-red-400" />
          <p className="text-sm font-semibold">Authentication Failed</p>
          <p className="text-xs text-red-300/80 text-center max-w-xs">
            Unable to authenticate before upload. Retry authentication to enable ingestion.
          </p>
          <button
            onClick={() => retryLogin()}
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-2 rounded text-xs font-semibold transition-colors"
          >
            Retry Authentication
          </button>
        </div>
      ) : (
        <label
          onDragOver={(e) => { e.preventDefault(); setIsHovering(true); }}
          onDragLeave={() => setIsHovering(false)}
          onDrop={handleDrop}
          className={`w-full h-40 border-2 border-dashed rounded-xl flex flex-col items-center justify-center transition-colors cursor-pointer ${
            isHovering
              ? 'border-cyan-500 bg-cyan-950/20 text-cyan-400'
              : 'border-slate-700 bg-slate-900 text-slate-400 hover:border-cyan-500 hover:text-cyan-400'
          }`}
        >
          <input
            type="file"
            accept=".csv"
            className="hidden"
            onChange={handleFileSelect}
            disabled={!authReady}
          />

          {status === 'uploading' && (
            <>
              <Loader2 className="w-10 h-10 mb-3 animate-spin text-cyan-400" />
              <p className="text-sm font-semibold text-cyan-400">Ingesting into DuckDB...</p>
            </>
          )}

          {status === 'success' && (
            <>
              <CheckCircle className="w-10 h-10 mb-3 text-emerald-400" />
              <p className="text-sm font-semibold text-emerald-400">File Ingested Successfully!</p>
            </>
          )}

          {status === 'error' && (
            <>
              <AlertCircle className="w-10 h-10 mb-3 text-rose-400" />
              <p className="text-sm font-semibold text-rose-400">Upload Failed</p>
              <p className="text-xs text-rose-300 mt-1 max-w-xs text-center">{errorMessage}</p>
            </>
          )}

          {status === 'idle' && (
            <>
              <UploadCloud className="w-10 h-10 mb-3" />
              <p className="text-sm font-semibold text-white">
                {authReady ? 'Drag & drop your CSV ledger here, or click to browse' : 'Authenticating...'}
              </p>
              <p className="text-xs mt-1">Uploading as tenant: <span className="text-cyan-400 font-mono">{clientId}</span></p>
            </>
          )}
        </label>
      )}
    </div>
  );
}
