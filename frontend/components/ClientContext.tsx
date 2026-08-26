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
  login: (email: string, password: string) => Promise<AuthResult>;
  signup: (companyName: string, email: string, password: string) => Promise<AuthResult>;
  logout: () => void;
  // Kept for SwarmLogStreamer's existing "Retry Authentication" button --
  // re-validates whatever token is currently stored, without forcing a
  // fresh login. A real 401 from that re-check still routes back to
  // AuthGate's login form (authToken/user both clear), same as any other
  // expired-token path.
  retryLogin: () => void;
}

const ClientContext = createContext<ClientContextType | undefined>(undefined);

const TOKEN_STORAGE_KEY = 'nexus_access_token';

function backendUrl(): string {
  return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
}

export function ClientProvider({ children }: { children: ReactNode }) {
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthedUser | null>(null);
  const [authReady, setAuthReady] = useState<boolean>(false);
  const [checkAttempt, setCheckAttempt] = useState<number>(0);

  const applyAuthResponse = useCallback((body: {
    access_token: string; user_id: number; client_id: string; email: string; role: string;
  }) => {
    setAuthToken(body.access_token);
    setUser({ userId: body.user_id, clientId: body.client_id, email: body.email, role: body.role as UserRole });
    if (typeof window !== 'undefined') {
      sessionStorage.setItem(TOKEN_STORAGE_KEY, body.access_token);
    }
  }, []);

  const clearAuth = useCallback(() => {
    setAuthToken(null);
    setUser(null);
    if (typeof window !== 'undefined') {
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  }, []);

  // On mount (and on retryLogin), validate whatever token is already in
  // sessionStorage from an earlier session -- real /api/v1/auth/me call,
  // not just trusting a locally-decoded, unverified JWT payload. A 401
  // here (expired/tampered/stale token) clears it and drops straight to
  // AuthGate's login form rather than an app stuck half-authenticated.
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
        const res = await fetch(`${backendUrl()}/api/v1/auth/me`, {
          headers: { Authorization: `Bearer ${stored}` },
        });
        if (!res.ok) throw new Error(`Session check failed: ${res.status}`);
        const me = await res.json();
        if (cancelled) return;
        setAuthToken(stored);
        setUser({ userId: me.user_id, clientId: me.client_id, email: me.email, role: me.role as UserRole });
      } catch (err) {
        console.warn("Stored session is no longer valid -- signing out:", err);
        if (!cancelled) clearAuth();
      } finally {
        if (!cancelled) setAuthReady(true);
      }
    }

    restoreSession();
    return () => { cancelled = true; };
  }, [checkAttempt, clearAuth]);

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

  const logout = useCallback(() => {
    clearAuth();
  }, [clearAuth]);

  const retryLogin = useCallback(() => setCheckAttempt((n) => n + 1), []);

  return (
    <ClientContext.Provider
      value={{
        clientId: user?.clientId ?? '',
        authToken,
        authReady,
        user,
        login,
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
