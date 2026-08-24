'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

interface ClientContextType {
  clientId: string;
  setClientId: (id: string) => void;
  // Added 2026-08-22: real (not fabricated) auth wiring. authToken is a
  // genuine, validly-signed JWT minted by the backend's temporary
  // /api/v1/auth/dev-login endpoint (no password check -- see that
  // endpoint's own comment in main.py for why). authReady tells consumers
  // whether that login attempt has resolved (success OR failure) yet, so
  // widgets can wait for it instead of firing their data fetch with no
  // token on first mount and never retrying.
  authToken: string | null;
  authReady: boolean;
}

const ClientContext = createContext<ClientContextType | undefined>(undefined);

const TOKEN_STORAGE_KEY = 'nexus_access_token';

export function ClientProvider({ children }: { children: ReactNode }) {
  const [clientId, setClientId] = useState<string>('CLI-001');
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;

    async function devLogin() {
      setAuthReady(false);
      try {
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
        const res = await fetch(`${backendUrl}/api/v1/auth/dev-login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ client_id: clientId }),
        });
        if (!res.ok) {
          throw new Error(`Dev login failed: ${res.status}`);
        }
        const result = await res.json();
        if (cancelled) return;
        setAuthToken(result.access_token);
        if (typeof window !== 'undefined') {
          sessionStorage.setItem(TOKEN_STORAGE_KEY, result.access_token);
        }
      } catch (err) {
        console.error("Dev login failed -- dashboard widgets will run unauthenticated:", err);
        if (!cancelled) {
          setAuthToken(null);
        }
      } finally {
        if (!cancelled) {
          setAuthReady(true);
        }
      }
    }

    devLogin();
    return () => { cancelled = true; };
  }, [clientId]);

  return (
    <ClientContext.Provider value={{ clientId, setClientId, authToken, authReady }}>
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
