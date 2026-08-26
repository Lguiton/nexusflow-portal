"use client";

import { useState } from "react";
import { Loader2, AlertCircle, LogIn, UserPlus } from "lucide-react";
import { useClientId } from "./ClientContext";

// RBAC-01: real login/signup gate, replacing the old auto-dev-login flow.
// Renders the login/signup form when there's no authenticated user yet;
// renders `children` (the real dashboard) once there is. This is the
// ONLY place in the app that should ever call login()/signup() directly
// -- every other widget just reads authToken/authReady/user from
// useClientId() the same way it always has.

type Mode = "login" | "signup";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { authReady, user, login, signup } = useClientId();
  const [mode, setMode] = useState<Mode>("login");
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!authReady) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-950 text-cyan-400 gap-3">
        <Loader2 className="w-8 h-8 animate-spin" />
        <p className="text-sm font-medium">Checking your session...</p>
      </div>
    );
  }

  if (user) {
    return <>{children}</>;
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
