'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';

export type UserRole = 'owner' | 'admin' | 'member' | 'viewer';

export interface AuthedUser {
  userId: number;
  clientId: string;
  email: string;
  role: UserRole;
}

interface AuthResult {
  ok: boolean;
  error?: string;
  // AUTH-04: set when login() succeeded on the PASSWORD step but this
  // account has MFA enabled -- no access_token exists yet at this point
  // (see backend/accounts.py's login(), which withholds one for exactly
  // this case). The caller (AuthGate) is expected to collect a 6-digit
  // code and call verifyMfaCode(mfaChallengeToken, code) to actually
  // finish signing in.
  mfaRequired?: boolean;
  mfaChallengeToken?: string;
}

interface ClientContextType {
  // '' when signed out -- real value comes from the authenticated user's
  // own tenant, never manually settable (RBAC-01: there used to be a
  // setClientId escape hatch here for the old dev-login flow's manual
  // "CLI-001" text field; a real per-user token makes that meaningless --
  // switching tenants now means logging in as a different real account).
  clientId: string;
  authToken: string | null;
  authReady: boolean;
  user: AuthedUser | null;
  // TEN-01/TEN-02: whether THIS tenant is currently suspended, and the raw
  // status string behind it ("active" | "suspended"). Populated from
  // login/signup/me's shared lifecycle fields (see backend/accounts.py's
  // _lifecycle_fields) -- never independently polled, so it's only as
  // fresh as the last auth call. refreshLifecycleStatus re-fetches it on
  // demand (e.g. right after a suspend/reactivate action) without a full
  // session-restore round trip.
  tenantSuspended: boolean;
  lifecycleStatus: string | null;
  refreshLifecycleStatus: () => Promise<void>;
  login: (email: string, password: string) => Promise<AuthResult>;
  // AUTH-04 step 2: completes a login that login() reported as
  // mfa_required, given the challenge token it returned and a real code
  // (TOTP from the authenticator app, or a backup code) from the user.
  verifyMfaCode: (challengeToken: string, code: string) => Promise<AuthResult>;
  signup: (companyName: string, email: string, password: string) => Promise<AuthResult>;
  // AUTH-02: now async -- best-effort revokes the refresh token server-
  // side (backend/accounts.py's logout()) before clearing local state.
  // Every existing call site (onClick={logout}, bare logout()) already
  // ignores the return value, so this stays a drop-in change.
  logout: () => Promise<void>;
  // Kept for SwarmLogStreamer's existing "Retry Authentication" button --
  // re-validates whatever token is currently stored, without forcing a
  // fresh login. A real 401 from that re-check still routes back to
  // AuthGate's login form (authToken/user both clear), same as any other
  // expired-token path.
  retryLogin: () => void;
}

const ClientContext = createContext<ClientContextType | undefined>(undefined);

const TOKEN_STORAGE_KEY = 'nexus_access_token';
// AUTH-02: the long-lived credential (backend/accounts.py's
// REFRESH_TOKEN_TTL_DAYS = 30). Stored alongside the access token so a
// returning tab can silently get a fresh access token instead of forcing
// a real re-login just because the short-lived one expired while the tab
// was idle.
const REFRESH_TOKEN_STORAGE_KEY = 'nexus_refresh_token';
// Matches backend/accounts.py's TOKEN_TTL_MINUTES (30) with real margin --
// refreshing every 10 minutes means even two back-to-back failed attempts
// (a network blip) still leave time for a third before the access token
// actually expires. Keep this comfortably under half of TOKEN_TTL_MINUTES
// if that backend constant ever changes.
const PROACTIVE_REFRESH_INTERVAL_MS = 10 * 60 * 1000;

function backendUrl(): string {
  return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
}

export function ClientProvider({ children }: { children: ReactNode }) {
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthedUser | null>(null);
  const [authReady, setAuthReady] = useState<boolean>(false);
  const [checkAttempt, setCheckAttempt] = useState<number>(0);
  const [lifecycleStatus, setLifecycleStatus] = useState<string | null>(null);

  const applyAuthResponse = useCallback((body: {
    access_token: string; refresh_token?: string; user_id: number; client_id: string; email: string; role: string;
    lifecycle_status?: string;
  }) => {
    setAuthToken(body.access_token);
    setUser({ userId: body.user_id, clientId: body.client_id, email: body.email, role: body.role as UserRole });
    setLifecycleStatus(body.lifecycle_status ?? 'active');
    if (typeof window !== 'undefined') {
      sessionStorage.setItem(TOKEN_STORAGE_KEY, body.access_token);
      // refresh_token is present on every real login/signup/mfa-verify/
      // refresh response -- optional here only so this same function can
      // still type-check against a hand-built object in tests.
      if (body.refresh_token) {
        sessionStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, body.refresh_token);
      }
    }
  }, []);

  const clearAuth = useCallback(() => {
    setAuthToken(null);
    setUser(null);
    setLifecycleStatus(null);
    if (typeof window !== 'undefined') {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
      sessionStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
    }
  }, []);

  // AUTH-02: exchanges whatever refresh token is currently stored for a
  // fresh access+refresh pair via POST /api/v1/auth/refresh, applying the
  // result the same way a login response would be. Returns whether it
  // succeeded so callers (session restore, the proactive timer below) can
  // each decide what to do next -- this function itself never clears
  // auth state on failure, since a stale in-memory session is still
  // better than none while the caller decides.
  const performRefresh = useCallback(async (): Promise<boolean> => {
    const storedRefresh = typeof window !== 'undefined' ? sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY) : null;
    if (!storedRefresh) return false;
    try {
      const res = await fetch(`${backendUrl()}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: storedRefresh }),
      });
      if (!res.ok) return false;
      const body = await res.json();
      applyAuthResponse(body);
      return true;
    } catch (err) {
      console.warn('Token refresh failed:', err);
      return false;
    }
  }, [applyAuthResponse]);

  // On mount (and on retryLogin), validate whatever token is already in
  // sessionStorage from an earlier session -- real /api/v1/auth/me call,
  // not just trusting a locally-decoded, unverified JWT payload. A 401
  // here now most likely just means the short-lived access token expired
  // while this tab was idle (AUTH-02 shortened it from 12 hours to 30
  // minutes) -- not that the whole session is invalid -- so this tries a
  // real refresh before giving up and dropping to AuthGate's login form.
  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      setAuthReady(false);
      const stored = typeof window !== 'undefined' ? sessionStorage.getItem(TOKEN_STORAGE_KEY) : null;
      if (!stored) {
        if (!cancelled) {
          clearAuth();
          setAuthReady(true);
        }
        return;
      }
      try {
        // TEN-01/TEN-02: /me deliberately stays reachable even for a
        // suspended tenant (see backend/accounts.py's get_me) -- a 423 here
        // would otherwise be indistinguishable from "your token is
        // invalid" below and silently bounce a suspended tenant's owner
        // back to the login form instead of showing AuthGate's suspended
        // screen.
        const res = await fetch(`${backendUrl()}/api/v1/auth/me`, {
          headers: { Authorization: `Bearer ${stored}` },
        });
        if (!res.ok) {
          // AUTH-02: the access token itself may just be expired -- try a
          // real refresh (which needs the refresh token, not this one)
          // before concluding the whole session is gone.
          const refreshed = await performRefresh();
          if (!refreshed) throw new Error(`Session check failed: ${res.status}`);
          if (!cancelled) setAuthReady(true);
          return;
        }
        const me = await res.json();
        if (cancelled) return;
        setAuthToken(stored);
        setUser({ userId: me.user_id, clientId: me.client_id, email: me.email, role: me.role as UserRole });
        setLifecycleStatus(me.lifecycle_status ?? 'active');
      } catch (err) {
        console.warn("Stored session is no longer valid -- signing out:", err);
        if (!cancelled) clearAuth();
      } finally {
        if (!cancelled) setAuthReady(true);
      }
    }

    restoreSession();
    return () => { cancelled = true; };
  }, [checkAttempt, clearAuth, performRefresh]);

  // AUTH-02: proactive background refresh -- rather than wait for a 401
  // from one of the ~20+ components that fetch with authToken directly
  // (which would mean touching every one of them to retry after a
  // refresh), silently mint a fresh access+refresh pair on a timer while
  // signed in, comfortably inside the access token's real lifetime. A
  // signed-out tab (authToken null) runs no timer at all.
  useEffect(() => {
    if (!authToken) return;
    const intervalId = setInterval(() => {
      performRefresh();
    }, PROACTIVE_REFRESH_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [authToken, performRefresh]);

  const login = useCallback(async (email: string, password: string): Promise<AuthResult> => {
    try {
      const res = await fetch(`${backendUrl()}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        return { ok: false, error: body.detail || `Login failed (${res.status})` };
      }
      // AUTH-04: the password was right, but this account has MFA
      // enabled -- backend/accounts.py's login() withholds a real
      // access_token in this case (returns mfa_required + a short-lived
      // challenge token instead), so there's nothing to applyAuthResponse
      // yet. The caller must collect a code and call verifyMfaCode.
      if (body.mfa_required) {
        return { ok: true, mfaRequired: true, mfaChallengeToken: body.mfa_challenge_token };
      }
      applyAuthResponse(body);
      return { ok: true };
    } catch (err: any) {
      return { ok: false, error: err?.message || "Could not reach the server." };
    }
  }, [applyAuthResponse]);

  const verifyMfaCode = useCallback(async (challengeToken: string, code: string): Promise<AuthResult> => {
    try {
      const res = await fetch(`${backendUrl()}/api/v1/auth/mfa/verify`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${challengeToken}`,
        },
        body: JSON.stringify({ code }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        return { ok: false, error: body.detail || `Verification failed (${res.status})` };
      }
      applyAuthResponse(body);
      return { ok: true };
    } catch (err: any) {
      return { ok: false, error: err?.message || "Could not reach the server." };
    }
  }, [applyAuthResponse]);

  const signup = useCallback(async (companyName: string, email: string, password: string): Promise<AuthResult> => {
    try {
      const res = await fetch(`${backendUrl()}/api/v1/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_name: companyName, email, password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = Array.isArray(body.detail)
          ? body.detail.map((d: any) => d.msg).join("; ") // pydantic 422 shape
          : body.detail;
        return { ok: false, error: detail || `Signup failed (${res.status})` };
      }
      applyAuthResponse(body);
      return { ok: true };
    } catch (err: any) {
      return { ok: false, error: err?.message || "Could not reach the server." };
    }
  }, [applyAuthResponse]);

  const logout = useCallback(async () => {
    // AUTH-02: best-effort server-side revoke of the refresh token so it
    // can't be used again even if it somehow leaked -- but local sign-out
    // must not depend on this succeeding (the network could be down, or
    // the token could already be invalid) so failures here are swallowed
    // and clearAuth() always runs.
    const storedRefresh = typeof window !== 'undefined' ? sessionStorage.getItem(REFRESH_TOKEN_STORAGE_KEY) : null;
    if (storedRefresh) {
      try {
        await fetch(`${backendUrl()}/api/v1/auth/logout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: storedRefresh }),
        });
      } catch (err) {
        console.warn('Server-side logout call failed (signing out locally anyway):', err);
      }
    }
    clearAuth();
  }, [clearAuth]);

  const retryLogin = useCallback(() => setCheckAttempt((n) => n + 1), []);

  // TEN-01/TEN-02: cheap re-fetch of just the lifecycle status, for
  // TenantLifecycleCard to call right after a suspend/reactivate action so
  // the rest of the app (AuthGate's blocking screen, in particular) picks
  // up the new state immediately -- without re-running the whole
  // session-restore flow (and its loading spinner) via retryLogin.
  const refreshLifecycleStatus = useCallback(async () => {
    if (!authToken) return;
    try {
      const res = await fetch(`${backendUrl()}/api/v1/tenant/status`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!res.ok) return;
      const data = await res.json();
      setLifecycleStatus(data.lifecycle_status ?? 'active');
    } catch (err) {
      console.warn('Could not refresh tenant lifecycle status:', err);
    }
  }, [authToken]);

  return (
    <ClientContext.Provider
      value={{
        clientId: user?.clientId ?? '',
        authToken,
        authReady,
        user,
        tenantSuspended: lifecycleStatus === 'suspended',
        lifecycleStatus,
        refreshLifecycleStatus,
        login,
        verifyMfaCode,
        signup,
        logout,
        retryLogin,
      }}
    >
      {children}
    </ClientContext.Provider>
  );
}

export function useClientId() {
  const context = useContext(ClientContext);
  if (context === undefined) {
    throw new Error('useClientId must be used within a ClientProvider');
  }
  return context;
}
