'use client';

import React, { useState } from 'react';
import { UploadCloud, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';

export default function ETLDropzone() {
  const [isHovering, setIsHovering] = useState(false);
  const [status, setStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  
  // NEW: State to hold our simulated authentication token
  const [clientId, setClientId] = useState<string>('AGENCY-123');

  const handleFileUpload = async (file: File) => {
    setStatus('uploading');
    setErrorMessage(null);

    const formData = new FormData();
    formData.append('file', file);

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

    try {
      const res = await fetch(`${apiUrl}/api/finance/upload-ledger`, {
        method: 'POST',
        // NEW: We inject the Client ID into the headers securely
        headers: {
          'X-Client-ID': clientId,
        },
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || 'Failed to upload ledger.');
      }

      setStatus('success');
      setTimeout(() => setStatus('idle'), 4000);
    } catch (err: any) {
      console.error("Upload error:", err);
      setStatus('error');
      setErrorMessage(err.message || 'Network error connecting to FastAPI backend.');
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
        
        {/* NEW: A simple UI toggle to test multi-tenancy isolation */}
        <div className="flex items-center gap-2 bg-slate-900 px-3 py-2 rounded-lg border border-slate-800">
          <label className="text-xs font-medium text-slate-400">Simulate Client:</label>
          <input
            type="text"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="bg-slate-950 border border-slate-700 text-cyan-400 text-xs px-2 py-1 rounded w-28 focus:outline-none focus:border-cyan-500 font-mono"
            title="Change this to simulate a different logged-in user"
          />
        </div>
      </div>

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
            <p className="text-sm font-semibold text-white">Drag & drop your CSV ledger here, or click to browse</p>
            <p className="text-xs mt-1">Uploading as tenant: <span className="text-cyan-400 font-mono">{clientId}</span></p>
          </>
        )}
      </label>
    </div>
  );
}