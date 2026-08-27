"use client";

import React, { useEffect, useState } from "react";
import { ShieldCheck, Loader2, CheckCircle2, AlertCircle, Copy, KeyRound } from "lucide-react";
import { useClientId } from "./ClientContext";

// AUTH-04: lets any signed-in person enroll/disenroll their OWN TOTP
// second factor (never someone else's -- every endpoint this card calls
// is scoped to the caller's own account by verify_jwt_and_get_user, no
// user_id parameter exists on any of them). Three real steps against the
// real backend, no client-side crypto: /mfa/setup generates a secret and
// renders a QR server-side, /mfa/enable confirms it with a real code from
// the authenticator app and returns backup codes (shown here exactly
// once, in plaintext, then never again), and /mfa/disable requires BOTH
// the current password and a valid code before turning it off.
type Stage = "loading" | "off" | "enrolling" | "backup_codes_shown" | "on";

export default function MfaSettingsCard() {
  const clientCtx = useClientId() as any;
  const authToken: string | null = clientCtx?.authToken ?? null;
  const authReady: boolean = clientCtx?.authReady ?? false;

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  const authHeaders: Record<string, string> = authToken ? { Authorization: `Bearer ${authToken}` } : {};

  const [stage, setStage] = useState<Stage>("loading");
  const [backupCodesRemaining, setBackupCodesRemaining] = useState<number>(0);
  const [secret, setSecret] = useState<string | null>(null);
  const [qrDataUri, setQrDataUri] = useState<string | null>(null);
  const [enrollCode, setEnrollCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [copied, setCopied] = useState(false);

  const [disablePassword, setDisablePassword] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [showDisableForm, setShowDisableForm] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = async () => {
    try {
      const res = await fetch(`${backendUrl}/api/v1/auth/mfa/status`, { headers: authHeaders });
      if (!res.ok) return;
      const data = await res.json();
      setBackupCodesRemaining(data.backup_codes_remaining ?? 0);
      setStage(data.enabled ? "on" : "off");
    } catch (err) {
      console.error("MFA status check failed:", err);
    }
  };

  useEffect(() => {
    if (!authReady) return;
    refreshStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady]);

  const handleStartEnroll = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/auth/mfa/setup`, { method: "POST", headers: authHeaders });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      const data = await res.json();
      setSecret(data.secret);
      setQrDataUri(data.qr_code_data_uri);
      setEnrollCode("");
      setStage("enrolling");
    } catch (err: any) {
      setError(err.message || "Could not start MFA setup.");
    } finally {
      setBusy(false);
    }
  };

  const handleConfirmEnroll = async () => {
    if (!enrollCode.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/auth/mfa/enable`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ code: enrollCode.trim() }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      setBackupCodes(body.backup_codes || []);
      setStage("backup_codes_shown");
    } catch (err: any) {
      setError(err.message || "Incorrect code -- please try again.");
    } finally {
      setBusy(false);
    }
  };

  const handleDoneWithBackupCodes = () => {
    setBackupCodes([]);
    refreshStatus();
  };

  const handleCopyBackupCodes = async () => {
    try {
      await navigator.clipboard.writeText(backupCodes.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Clipboard copy failed:", err);
    }
  };

  const handleDisable = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${backendUrl}/api/v1/auth/mfa/disable`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({ password: disablePassword, code: disableCode.trim() }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body.detail || `Server status: ${res.status}`);
      }
      setDisablePassword("");
      setDisableCode("");
      setShowDisableForm(false);
      await refreshStatus();
    } catch (err: any) {
      setError(err.message || "Could not disable MFA.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-cyan-500/10 border border-cyan-500/20 rounded-lg">
          <ShieldCheck className="w-5 h-5 text-cyan-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Two-Factor Authentication</h2>
          <p className="text-xs text-slate-400">Require a code from an authenticator app on top of your password.</p>
        </div>
      </div>

      <div className="p-6">
        {stage === "loading" && (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
            <Loader2 className="w-4 h-4 animate-spin" />
            Checking status...
          </div>
        )}

        {stage === "off" && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm">
              <AlertCircle className="w-4 h-4 text-slate-500" />
              <span className="text-slate-500">Not enabled -- your account only requires a password to sign in.</span>
            </div>
            <button
              onClick={handleStartEnroll}
              disabled={busy}
              className="bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors flex items-center gap-2"
            >
              {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Enable two-factor authentication
            </button>
            {error && <p className="text-xs text-rose-400">{error}</p>}
          </div>
        )}

        {stage === "enrolling" && (
          <div className="space-y-4">
            <p className="text-xs text-slate-400">
              Scan this QR code with an authenticator app (Google Authenticator, 1Password, Authy), then enter the 6-digit code it shows.
            </p>
            {qrDataUri && (
              <div className="bg-white rounded-lg p-3 w-fit">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={qrDataUri} alt="MFA enrollment QR code" className="w-40 h-40" />
              </div>
            )}
            {secret && (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <KeyRound className="w-3.5 h-3.5" />
                <span>Can't scan? Enter manually:</span>
                <code className="bg-slate-950 border border-slate-800 rounded px-2 py-1 text-slate-300 tracking-wider">{secret}</code>
              </div>
            )}
            <div className="flex gap-2">
              <input
                type="text"
                value={enrollCode}
                onChange={(e) => setEnrollCode(e.target.value)}
                placeholder="123456"
                className="flex-1 bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm text-slate-100 placeholder-slate-600 tracking-widest text-center focus:outline-none focus:border-cyan-500 transition-colors"
              />
              <button
                onClick={handleConfirmEnroll}
                disabled={busy || !enrollCode.trim()}
                className="bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors flex items-center gap-2"
              >
                {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Confirm
              </button>
            </div>
            {error && <p className="text-xs text-rose-400">{error}</p>}
            <button
              onClick={() => { setStage("off"); setError(null); }}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              Cancel
            </button>
          </div>
        )}

        {stage === "backup_codes_shown" && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span className="text-slate-300">Two-factor authentication is now enabled.</span>
            </div>
            <div className="bg-amber-950/20 border border-amber-900/40 rounded-lg p-4 space-y-3">
              <p className="text-xs text-amber-300 font-semibold">
                Save these backup codes now -- each works once if you lose access to your authenticator app, and they are shown only this one time.
              </p>
              <div className="grid grid-cols-2 gap-2">
                {backupCodes.map((c) => (
                  <code key={c} className="bg-slate-950 border border-slate-800 rounded px-2 py-1 text-xs text-slate-200 text-center tracking-wider">{c}</code>
                ))}
              </div>
              <button
                onClick={handleCopyBackupCodes}
                className="flex items-center gap-1.5 text-xs text-amber-300 hover:text-amber-200 transition-colors"
              >
                <Copy className="w-3.5 h-3.5" />
                {copied ? "Copied!" : "Copy all codes"}
              </button>
            </div>
            <button
              onClick={handleDoneWithBackupCodes}
              className="bg-cyan-600 hover:bg-cyan-500 text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors"
            >
              I've saved these codes
            </button>
          </div>
        )}

        {stage === "on" && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span className="text-slate-300">Enabled -- {backupCodesRemaining} backup code{backupCodesRemaining === 1 ? "" : "s"} remaining.</span>
            </div>

            {!showDisableForm ? (
              <button
                onClick={() => { setShowDisableForm(true); setError(null); }}
                className="text-xs text-rose-400 hover:text-rose-300 transition-colors"
              >
                Disable two-factor authentication
              </button>
            ) : (
              <div className="space-y-3 bg-slate-950/50 border border-slate-800 rounded-lg p-4">
                <p className="text-xs text-slate-400">Confirm your password and a current code to disable two-factor authentication.</p>
                <input
                  type="password"
                  value={disablePassword}
                  onChange={(e) => setDisablePassword(e.target.value)}
                  placeholder="Password"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-rose-500 transition-colors"
                />
                <input
                  type="text"
                  value={disableCode}
                  onChange={(e) => setDisableCode(e.target.value)}
                  placeholder="Authenticator or backup code"
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg py-2 px-3 text-sm text-slate-100 placeholder-slate-600 tracking-wider focus:outline-none focus:border-rose-500 transition-colors"
                />
                <div className="flex gap-2">
                  <button
                    onClick={handleDisable}
                    disabled={busy || !disablePassword || !disableCode.trim()}
                    className="bg-rose-600 hover:bg-rose-500 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors flex items-center gap-2"
                  >
                    {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    Confirm disable
                  </button>
                  <button
                    onClick={() => { setShowDisableForm(false); setDisablePassword(""); setDisableCode(""); setError(null); }}
                    className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
            {error && <p className="text-xs text-rose-400">{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
