"use client";

import React, { useState, useRef } from 'react';
import { UploadCloud, CheckCircle, AlertCircle, Loader2, Database } from 'lucide-react';
import { useClientId } from "./ClientContext"; 

const MAX_FILE_SIZE = 50 * 1024 * 1024; 

interface FileDropzoneProps {
  onUploadSuccess?: () => void;
}

export default function FileDropzone({ onUploadSuccess }: FileDropzoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const [status, setStatus] = useState<'IDLE' | 'UPLOADING' | 'SUCCESS' | 'ERROR'>('IDLE');
  const [message, setMessage] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  
  let currentClientId = "default_client";
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId) {
      currentClientId = clientCtx.clientId;
    }
  } catch (e) { }

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") setDragActive(true);
    else if (e.type === "dragleave") setDragActive(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) await uploadFile(e.dataTransfer.files[0]);
  };

  const handleChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) await uploadFile(e.target.files[0]);
  };

  const uploadFile = async (file: File) => {
    if (file.type !== "text/csv" && !file.name.toLowerCase().endsWith('.csv')) {
      setStatus('ERROR'); setMessage('Security Policy: Only valid CSV files are permitted.'); return;
    }
    if (file.size > MAX_FILE_SIZE) {
      setStatus('ERROR'); setMessage('Security Block: Payload exceeds the 50MB threshold.'); return;
    }

    setStatus('UPLOADING');
    const safeFileName = file.name.replace(/[^a-zA-Z0-9.\-_]/g, '_');
    const safeFile = new File([file], safeFileName, { type: file.type });
    const formData = new FormData();
    formData.append('file', safeFile);

    try {
      const token = typeof window !== 'undefined' ? sessionStorage.getItem('nexus_access_token') : null;
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

      const res = await fetch(`${backendUrl}/api/finance/upload-ledger`, {
        method: 'POST',
        headers: { 
          'x-client-id': currentClientId,
          ...(token ? { 'Authorization': `Bearer ${token}` } : {})
        },
        body: formData
      });
      
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Ingestion pipeline rejected the payload.');
      }
      
      setStatus('SUCCESS');
      setMessage(`Successfully validated and ingested ${safeFileName} into DuckDB.`);
      
      // BUG B FIXED: Tell the parent page that new data exists!
      if (onUploadSuccess) {
        onUploadSuccess();
      }
    } catch (err: any) {
      setStatus('ERROR');
      setMessage(err.message || 'An error occurred during secure upload.');
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-2xl">
      <div className="mb-4 flex items-center gap-2">
        <Database className="w-5 h-5 text-indigo-400" />
        <div>
          <h3 className="text-slate-100 font-semibold text-sm">Automated Data Ingestion (DuckDB)</h3>
          <p className="text-slate-400 text-xs">Drop CSVs here to safely ingest structured financial logs.</p>
        </div>
      </div>
      <div 
        className={`relative border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center transition-all cursor-pointer ${
          dragActive ? 'border-indigo-500 bg-indigo-950/20 scale-[1.02]' : 'border-slate-700 bg-slate-950/50 hover:border-slate-500'
        } ${status === 'UPLOADING' ? 'opacity-50 pointer-events-none' : ''}`}
        onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input ref={inputRef} type="file" accept=".csv" onChange={handleChange} className="hidden" />
        
        {status === 'IDLE' && (
          <>
            <UploadCloud className="w-10 h-10 text-slate-400 mb-3" />
            <p className="text-slate-200 text-sm font-medium">Drag & drop your CSV ledger here, or click to browse</p>
          </>
        )}
        {status === 'UPLOADING' && (
          <>
            <Loader2 className="w-10 h-10 text-indigo-400 animate-spin mb-3" />
            <p className="text-slate-200 text-sm font-medium">Ingesting into DuckDB & Validating Schema...</p>
          </>
        )}
        {status === 'SUCCESS' && (
          <>
            <CheckCircle className="w-10 h-10 text-emerald-400 mb-3" />
            <p className="text-emerald-400 text-sm font-medium">Data Embedded Successfully</p>
            <p className="text-slate-400 text-xs mt-1">{message}</p>
          </>
        )}
        {status === 'ERROR' && (
          <>
            <AlertCircle className="w-10 h-10 text-red-400 mb-3" />
            <p className="text-red-400 text-sm font-medium">Ingestion Failed</p>
            <p className="text-slate-400 text-xs mt-1">{message}</p>
          </>
        )}
      </div>
    </div>
  );
}
