"use client";

import React, { useEffect, useState } from "react";
import { Monitor, Loader2, AlertCircle, LogOut, ShieldAlert } from "lucide-react";
import { useClientId } from "./ClientContext";

// AUTH-06: lets any signed-in person see and manage their OWN active
// sessions (never someone else's -- every endpoint this card calls is
// scoped to the caller's own user_id server-side, no user_id parameter
// exists on any of them). A "session" here is one refresh-token rotation
// chain (see backend/db_manager.py's list_active_sessions_for_user) --
// signing one out revokes its refresh token so it can never mint a new
// access token again, though that device's CURRENT access token (if any)
// still works until it naturally expires (see backend/accounts.py's
// revoke_session_for_user/revoke_all_sessions docstrings for why a
// stateless JWT can't be revoked early).
interface SessionInfo {
  session_id: number;
  device_label: string | null;
  session_started_at: string | null;
  last_active_at: string | null;
  expires_at: string | null;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "Unknown";
  try {
    // DuckDB TIMESTAMPs serialize with no timezone suffix but are always
    // UTC internally -- append one before parsing so this doesn't get
    // silently mis-read as local time in the browser.
    const withZone = /[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`;
    return new Date(withZone).toLocaleString();
  } catch {
    return "Unknown";
  }
}

export default function SessionsCard() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;
  const logout: () => Promise<void> = clientCtx?.logout ?? (async () => {});

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  const authHeaders: Record<string, string> = authToken ? { Authorization: `Bearer ${authToken}` } : {};

  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<number | null>(null);
  const [showSignOutAllConfirm, setShowSignOutAllConfirm] = useState(false);
  const [signingOutAll, setSigningOutAll] = useState(false);

  const refreshSessions = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/v1/auth/sessions`, { headers: authHeaders });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      const data = await res.json();
      setSessions(data.sessions || []);
    } catch (err: any) {
      setError(err.message || "Could not load your active sessions.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authReady) return;
    setLoading(true);
    refreshSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady]);

  const handleRevoke = async (sessionId: number) => {
    setRevokingId(sessionId);
    setError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/auth/sessions/${sessionId}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
    } catch (err: any) {
      setError(err.message || "Could not sign out that device.");
    } finally {
      setRevokingId(null);
    }
  };

  const handleSignOutAll = async () => {
    setSigningOutAll(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/auth/sessions/revoke-all`, {
        method: "POST",
        headers: authHeaders,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      // This also revoked the CURRENT device's session -- clear local
      // state immediately rather than let this device keep working off
      // an access token that's now only alive until it naturally expires.
      await logout();
    } catch (err: any) {
      setError(err.message || "Could not sign out of all devices.");
      setSigningOutAll(false);
      setShowSignOutAllConfirm(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-teal-500/10 border border-teal-500/20 rounded-lg">
          <Monitor className="w-5 h-5 text-teal-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Active Sessions</h2>
          <p className="text-xs text-slate-400">See and sign out the devices currently signed in to your account.</p>
        </div>
      </div>

      <div className="p-6">
        {loading ? (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading sessions...
          </div>
        ) : sessions.length === 0 ? (
          <div className="flex items-center gap-2 text-sm">
            <AlertCircle className="w-4 h-4 text-slate-500" />
            <span className="text-slate-500">No active sessions found.</span>
          </div>
        ) : (
          <div className="space-y-3">
            {sessions.map((s) => (
              <div
                key={s.session_id}
                className="flex items-center justify-between gap-3 bg-slate-950/50 border border-slate-800 rounded-lg p-3"
              >
                <div className="min-w-0">
                  <p className="text-sm text-slate-200 font-medium truncate">{s.device_label || "Unknown device"}</p>
                  <p className="text-[11px] text-slate-500">
                    Signed in since {formatWhen(s.session_started_at)}
                  </p>
                </div>
                <button
                  onClick={() => handleRevoke(s.session_id)}
                  disabled={revokingId === s.session_id}
                  className="flex items-center gap-1.5 text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
                >
                  {revokingId === s.session_id ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <LogOut className="w-3.5 h-3.5" />
                  )}
                  Sign out
                </button>
              </div>
            ))}
          </div>
        )}

        {error && <p className="text-xs text-rose-400 mt-4">{error}</p>}

        <div className="mt-6 pt-4 border-t border-slate-800">
          {!showSignOutAllConfirm ? (
            <button
              onClick={() => setShowSignOutAllConfirm(true)}
              disabled={loading || sessions.length === 0}
              className="flex items-center gap-1.5 text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <ShieldAlert className="w-3.5 h-3.5" />
              Sign out of all devices
            </button>
          ) : (
            <div className="space-y-3 bg-rose-950/20 border border-rose-900/40 rounded-lg p-4">
              <p className="text-xs text-rose-300">
                This immediately signs out every device, including this one -- use it if you think your account may be compromised.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={handleSignOutAll}
                  disabled={signingOutAll}
                  className="bg-rose-600 hover:bg-rose-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors flex items-center gap-2"
                >
                  {signingOutAll && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Confirm sign out everywhere
                </button>
                <button
                  onClick={() => setShowSignOutAllConfirm(false)}
                  disabled={signingOutAll}
                  className="text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
