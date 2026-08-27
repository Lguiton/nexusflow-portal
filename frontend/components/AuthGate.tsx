"use client";

import { useState } from "react";
import { Loader2, AlertCircle, LogIn, UserPlus, ShieldAlert, LogOut, RefreshCw, ShieldCheck } from "lucide-react";
import { useClientId } from "./ClientContext";

// RBAC-01: real login/signup gate, replacing the old auto-dev-login flow.
// Renders the login/signup form when there's no authenticated user yet;
// renders `children` (the real dashboard) once there is. This is the
// ONLY place in the app that should ever call login()/signup() directly
// -- every other widget just reads authToken/authReady/user from
// useClientId() the same way it always has.
//
// TEN-01/TEN-02: also the ONE place that blocks the whole app for a
// SUSPENDED tenant, mirroring what the backend's suspension gate already
// does server-side (see backend/auth.py's _raise_if_suspended) -- without
// this, every individual widget would just show its own generic "fetch
// failed" error for a 423, which is confusing and tells nobody what's
// actually wrong or what to do about it.

type Mode = "login" | "signup";

function SuspendedScreen() {
  const { user, authToken, logout, refreshLifecycleStatus } = useClientId();
  const [reactivating, setReactivating] = useState(false);
  const [reactivateError, setReactivateError] = useState<string | null>(null);
  const isOwner = user?.role === "owner";

  const handleReactivate = async () => {
    setReactivating(true);
    setReactivateError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
      const res = await fetch(`${backendUrl}/api/v1/tenant/reactivate`, {
        method: "POST",
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      await refreshLifecycleStatus();
    } catch (err: any) {
      setReactivateError(err.message || "Could not reactivate this account.");
    } finally {
      setReactivating(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-md bg-slate-900 border border-amber-900/50 rounded-2xl shadow-lg p-6 text-center">
        <div className="mx-auto mb-4 w-12 h-12 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
          <ShieldAlert className="w-6 h-6 text-amber-400" />
        </div>
        <h1 className="text-lg font-bold text-white mb-2">This account is suspended</h1>
        <p className="text-sm text-slate-400 mb-5">
          {isOwner
            ? "You suspended this tenant. Reactivate it below to restore access for everyone on your team."
            : "An owner on your team has suspended this account. Contact them to have it reactivated."}
        </p>

        {reactivateError && (
          <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded-lg px-3 py-2 mb-4 text-left">
            <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <span>{reactivateError}</span>
          </div>
        )}

        <div className="flex flex-col gap-2">
          {isOwner && (
            <button
              onClick={handleReactivate}
              disabled={reactivating}
              className="w-full bg-amber-600 hover:bg-amber-500 text-white text-sm font-semibold rounded-lg px-3 py-2.5 flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {reactivating ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
              Reactivate this account
            </button>
          )}
          <button
            onClick={logout}
            className="w-full bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium rounded-lg px-3 py-2.5 flex items-center justify-center gap-2 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}

// AUTH-04: rendered in place of the login form once login() reports
// mfa_required -- collects a 6-digit authenticator code (or an 8-char
// backup code) and calls verifyMfaCode to actually finish signing in.
// The challenge token itself is short-lived (5 minutes, minted server-
// side) and useless for anything except this one call -- see
// backend/auth.py's verify_mfa_challenge_token / MfaChallenge.
function MfaCodeScreen({ challengeToken, onBack }: { challengeToken: string; onBack: () => void }) {
  const { verifyMfaCode } = useClientId();
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await verifyMfaCode(challengeToken, code.trim());
      if (!result.ok) {
        setError(result.error || "Incorrect code -- please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl shadow-lg p-6">
        <div className="flex items-center gap-2 mb-1">
          <ShieldCheck className="w-5 h-5 text-cyan-400" />
          <h1 className="text-lg font-bold text-white">Two-factor verification</h1>
        </div>
        <p className="text-xs text-slate-400 mb-5">
          Enter the 6-digit code from your authenticator app, or one of your backup codes.
        </p>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">Verification code</label>
            <input
              type="text"
              required
              autoFocus
              inputMode="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white tracking-widest text-center focus:outline-none focus:ring-1 focus:ring-cyan-500"
              placeholder="123456"
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded-lg px-3 py-2">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !code.trim()}
            className="w-full bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-semibold rounded-lg px-3 py-2.5 flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            Verify and sign in
          </button>
        </form>

        <button
          type="button"
          onClick={onBack}
          className="w-full text-center text-xs text-slate-400 hover:text-cyan-400 mt-4 transition-colors"
        >
          Back to sign in
        </button>
      </div>
    </div>
  );
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { authReady, user, tenantSuspended, login, signup } = useClientId();
  const [mode, setMode] = useState<Mode>("login");
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mfaChallengeToken, setMfaChallengeToken] = useState<string | null>(null);

  if (!authReady) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-950 text-cyan-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin" />
        <p className="text-sm font-medium">Checking your session...</p>
      </div>
    );
  }

  if (user && tenantSuspended) {
    return <SuspendedScreen />;
  }

  if (user) {
    return <>{children}</>;
  }

  if (mfaChallengeToken) {
    return <MfaCodeScreen challengeToken={mfaChallengeToken} onBack={() => setMfaChallengeToken(null)} />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = mode === "login"
        ? await login(email.trim(), password)
        : await signup(companyName.trim(), email.trim(), password);
      if (!result.ok) {
        setError(result.error || "Something went wrong -- please try again.");
      } else if (result.mfaRequired && result.mfaChallengeToken) {
        setMfaChallengeToken(result.mfaChallengeToken);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl shadow-lg p-6">
        <div className="flex items-center gap-2 mb-1">
          {mode === "login" ? (
            <LogIn className="w-5 h-5 text-cyan-400" />
          ) : (
            <UserPlus className="w-5 h-5 text-cyan-400" />
          )}
          <h1 className="text-lg font-bold text-white">
            {mode === "login" ? "Sign in to Eivanta" : "Create your Eivanta account"}
          </h1>
        </div>
        <p className="text-xs text-slate-400 mb-5">
          {mode === "login"
            ? "Use the email and password for your existing account."
            : "This creates a brand-new tenant and makes you its Owner."}
        </p>

        <form onSubmit={handleSubmit} className="space-y-3">
          {mode === "signup" && (
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Company name</label>
              <input
                type="text"
                required
                minLength={1}
                maxLength={200}
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-cyan-500"
                placeholder="Acme Inc."
              />
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-cyan-500"
              placeholder="you@company.com"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">Password</label>
            <input
              type="password"
              required
              minLength={mode === "signup" ? 8 : 1}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-cyan-500"
              placeholder={mode === "signup" ? "At least 8 characters" : "••••••••"}
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded-lg px-3 py-2">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-semibold rounded-lg px-3 py-2.5 flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button
          type="button"
          onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(null); }}
          className="w-full text-center text-xs text-slate-400 hover:text-cyan-400 mt-4 transition-colors"
        >
          {mode === "login" ? "Need an account? Sign up" : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}
