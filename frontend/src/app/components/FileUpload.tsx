'use client';

import React, { useState } from 'react';

export default function FileUpload() {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleUpload = async (file: File) => {
    if (!file.name.endsWith('.csv') && !file.name.endsWith('.json')) {
      setMessage({ type: 'error', text: 'Please upload a .csv or .json file.' });
      return;
    }

    setUploading(true);
    setMessage(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch("http://localhost:8000/api/v1/etl/upload", {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail | 'Upload failed');
      }

      const data = await res.json();
      setMessage({
        type: 'success',
        text: `Successfully ingested ${data.records_ingested} records from ${data.filename}! Refreshing dashboard...`,
      });

      setTimeout(() => {
        window.location.reload();
      }, 1500);
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message || 'Error uploading file' });
    } finally {
      setUploading(false);
    }
  };


  return (
    <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl mt-8">
      <h3 className="text-lg font-bold text-slate-100 mb-1">
        Automated DSP Ingestion Engine
      </h3>
      <p className="text-xs text-slate-400 mb-4">
        Drag and drop operational CSV/JSON datasets to trigger automated ETL sync.
      </p>

      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleUpload(e.dataTransfer.files[0]);
          }
        }}
        className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer ${isDragging ? 'border-cyan-400 bg-slate-800/50' : 'border-slate-700 bg-slate-950/50 hover:border-slate-600'}`}
        onClick={() => document.getElementById('file-input')?.click()}
      >
        <input
          id="file-input"
          type="file"
          accept=".csv,.json"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
        />
        {uploading ? (
          <p className="text-sm text-cyan-400 font-mono animate-pulse">
            Processing ETL Pipeline...
          </p>
        ) : (
          <div>
            <p className="text-sm font-medium text-slate-300">
              Drop dataset here or <span className="text-cyan-400 underline">browse</span>
            </p>
            <p className="text-xs text-slate-500 mt-1">Supports CSV, JSON (auto-transforms to PostgreS)</p>
          </div>
        )}
      </div>

      {message && (
        <div className={`mt-4 p-3 rounded-lg text-xs font-mono ${message.type === 'success' ? 'bg-emerald-950/50 border border-emerald-800 text-emerald-400' : 'bg-rose-950/50 border border-rose-800 text-rose-400'}`}>
          {message.text}
        </div>
      )}
    </div>
  );
}
