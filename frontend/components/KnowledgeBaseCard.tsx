"use client";

import React, { useCallback, useEffect, useState } from "react";
import { BookOpen, UploadCloud, Loader2, Search, Trash2, FileText, AlertCircle } from "lucide-react";
import { useClientId } from "./ClientContext";

// Track 3: persistent vector RAG knowledge base. Lets a tenant upload
// policy/SOP documents (.txt/.pdf) and semantically search them -- real
// OpenAI embeddings + real Qdrant storage on the backend (see
// backend/app/core/rag.py), not a mock.
interface KBDocument {
  doc_id: string;
  filename: string;
  chunk_count: number;
}

interface KBResult {
  content: string;
  filename: string;
  doc_id: string;
  score: number;
}

export default function KnowledgeBaseCard() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  const [documents, setDocuments] = useState<KBDocument[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<KBResult[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  const authHeaders = authToken ? { Authorization: `Bearer ${authToken}` } : {};

  const fetchDocuments = useCallback(async () => {
    if (!authReady) return;
    setLoadingDocs(true);
    try {
      const res = await fetch(`${backendUrl}/api/v1/knowledge/documents`, { headers: authHeaders });
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents ?? []);
      }
    } catch (err) {
      console.error("Knowledge base list failed:", err);
    } finally {
      setLoadingDocs(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, authToken, backendUrl]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${backendUrl}/api/v1/knowledge/upload`, {
        method: "POST",
        headers: authHeaders,
        body: formData,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      await fetchDocuments();
    } catch (err: any) {
      setUploadError(err.message || "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (docId: string) => {
    try {
      const res = await fetch(`${backendUrl}/api/v1/knowledge/documents/${docId}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (res.ok) {
        setDocuments((docs) => docs.filter((d) => d.doc_id !== docId));
      }
    } catch (err) {
      console.error("Knowledge base delete failed:", err);
    }
  };

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/knowledge/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ query: query.trim(), limit: 5 }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      const data = await res.json();
      setResults(data.results ?? []);
    } catch (err: any) {
      setSearchError(err.message || "Search failed.");
      setResults(null);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-violet-500/10 border border-violet-500/20 rounded-lg">
          <BookOpen className="w-5 h-5 text-violet-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Knowledge Base</h2>
          <p className="text-xs text-slate-400">Upload policy/SOP documents (.txt, .pdf) and search them semantically.</p>
        </div>
      </div>

      <div className="p-6 space-y-5">
        <label
          className={`flex flex-col items-center justify-center gap-2 border-2 border-dashed rounded-xl h-24 cursor-pointer transition-colors ${
            uploading ? "border-slate-700 text-slate-600" : "border-slate-700 text-slate-400 hover:border-violet-500 hover:text-violet-400"
          }`}
        >
          <input
            type="file"
            accept=".txt,.pdf"
            className="hidden"
            disabled={uploading || !authReady}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleUpload(f);
              e.target.value = "";
            }}
          />
          {uploading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="text-xs">Indexing document...</span>
            </>
          ) : (
            <>
              <UploadCloud className="w-5 h-5" />
              <span className="text-xs">Drop a .txt or .pdf here, or click to browse</span>
            </>
          )}
        </label>
        {uploadError && (
          <p className="text-xs text-rose-400 flex items-center gap-1.5">
            <AlertCircle className="w-3.5 h-3.5" /> {uploadError}
          </p>
        )}

        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">
            {loadingDocs ? "Loading..." : `${documents.length} document${documents.length === 1 ? "" : "s"} indexed`}
          </p>
          {!loadingDocs && documents.length === 0 && (
            <p className="text-xs text-slate-600 italic">No documents yet -- upload one above to get started.</p>
          )}
          <div className="space-y-1.5">
            {documents.map((doc) => (
              <div key={doc.doc_id} className="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs">
                <span className="flex items-center gap-2 text-slate-300 truncate">
                  <FileText className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                  {doc.filename}
                  <span className="text-slate-600">({doc.chunk_count} chunk{doc.chunk_count === 1 ? "" : "s"})</span>
                </span>
                <button
                  onClick={() => handleDelete(doc.doc_id)}
                  className="text-slate-600 hover:text-rose-400 transition-colors shrink-0 ml-2"
                  aria-label="Delete document"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="border-t border-slate-800 pt-4">
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="Ask something covered in your uploaded documents..."
              className="flex-1 bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-violet-500 transition-colors"
            />
            <button
              onClick={handleSearch}
              disabled={searching || !query.trim()}
              className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5"
            >
              {searching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
              Search
            </button>
          </div>

          {searchError && <p className="text-xs text-rose-400 mt-2">{searchError}</p>}

          {results && (
            <div className="mt-3 space-y-2">
              {results.length === 0 ? (
                <p className="text-xs text-slate-500 italic">No matches found.</p>
              ) : (
                results.map((r, i) => (
                  <div key={i} className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs">
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-violet-400 font-medium">{r.filename}</span>
                      <span className="text-slate-600 font-mono">{(r.score * 100).toFixed(0)}% match</span>
                    </div>
                    <p className="text-slate-400 leading-relaxed">{r.content}</p>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
