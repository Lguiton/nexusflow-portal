"use client";

import { useCallback, useEffect, useState } from "react";
import { Sparkles, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { useClientId } from "./ClientContext";

// DIFF-06: deterministic auto-categorization suggestions. Every suggestion
// is derived purely from this tenant's own already-categorized rows via
// real keyword overlap (see backend/db_manager.py's _suggest_category_for)
// -- never an LLM guess, and never applied without an explicit click here.
// See backend/categorization.py's module docstring for the founder
// decision behind "deterministic only" (2026-08-23).
interface CategorySuggestion {
  row_id: number;
  description: string;
  date: string;
  amount: number;
  suggested_category: string;
  confidence: number;
  matched_row_count: number;
}

interface CategorySuggestionsResponse {
  client_id: string;
  suggestions: CategorySuggestion[];
}

interface CategorySuggestionsWidgetProps {
  refreshTrigger?: number;
  onApplied?: () => void;
}

export default function CategorySuggestionsWidget({ refreshTrigger = 0, onApplied }: CategorySuggestionsWidgetProps) {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const [suggestions, setSuggestions] = useState<CategorySuggestion[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applyingRowId, setApplyingRowId] = useState<number | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  const fetchSuggestions = useCallback(async (signal?: AbortSignal) => {
    if (!authReady) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${backendUrl}/api/v1/data/category-suggestions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({}),
        signal,
      });
      if (!response.ok) {
        throw new Error(`Category suggestions lookup failed: ${response.status}`);
      }
      const json: CategorySuggestionsResponse = await response.json();
      setSuggestions(json.suggestions ?? []);
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("Category suggestions fetch failed:", err);
      setError(err.message || "Unable to load category suggestions right now.");
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, [authToken, authReady, backendUrl]);

  useEffect(() => {
    const controller = new AbortController();
    fetchSuggestions(controller.signal);
    return () => controller.abort();
  }, [fetchSuggestions, refreshTrigger]);

  const applySuggestion = async (rowId: number, newCategory: string) => {
    setApplyingRowId(rowId);
    setApplyError(null);
    try {
      const response = await fetch(`${backendUrl}/api/v1/data/apply-category-suggestion`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ row_id: rowId, new_category: newCategory }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Apply failed: ${response.status}`);
      }
      setSuggestions((prev) => (prev ? prev.filter((s) => s.row_id !== rowId) : prev));
      onApplied?.();
    } catch (err: any) {
      console.error("Apply category suggestion failed:", err);
      setApplyError(err.message || "Unable to apply this suggestion right now.");
    } finally {
      setApplyingRowId(null);
    }
  };

  const formatCurrency = (n: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-fuchsia-500/10 border border-fuchsia-500/20 rounded-lg">
          <Sparkles className="w-5 h-5 text-fuchsia-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Category Suggestions</h2>
          <p className="text-xs text-slate-400">Deterministic matches from your own categorized rows -- never applied automatically</p>
        </div>
      </div>

      <div className="p-6 flex-1">
        {error ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-slate-400">
            <AlertCircle className="w-8 h-8 text-rose-500/50" />
            <p className="text-sm">{error}</p>
          </div>
        ) : loading && !suggestions ? (
          <div className="flex flex-col items-center justify-center py-8 gap-3 text-fuchsia-400">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p className="text-sm font-medium">Looking for suggestions...</p>
          </div>
        ) : suggestions && suggestions.length === 0 ? (
          <p className="text-sm text-slate-500 italic py-4">No suggestions right now -- either everything's categorized or nothing matches closely enough.</p>
        ) : (
          <div className="space-y-3 animate-in fade-in duration-500">
            {applyError && (
              <p className="text-xs text-rose-400/90 mb-1">{applyError}</p>
            )}
            {(suggestions ?? []).map((s) => (
              <div key={s.row_id} className="border border-slate-800 rounded-lg p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-slate-200 truncate">{s.description}</p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {s.date} &middot; {formatCurrency(s.amount)}
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    Suggested: <span className="text-fuchsia-300 font-medium">{s.suggested_category}</span>
                    <span className="text-slate-600"> &middot; </span>
                    {Math.round(s.confidence * 100)}% confidence
                    <span className="text-slate-600"> &middot; </span>
                    {s.matched_row_count} matching row{s.matched_row_count === 1 ? "" : "s"}
                  </p>
                </div>
                <button
                  onClick={() => applySuggestion(s.row_id, s.suggested_category)}
                  disabled={applyingRowId === s.row_id}
                  className="text-xs bg-fuchsia-600/20 hover:bg-fuchsia-600/30 text-fuchsia-300 px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50 border border-fuchsia-700/40 shrink-0"
                >
                  {applyingRowId === s.row_id ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <CheckCircle2 className="w-3 h-3" />
                  )}
                  Accept
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
