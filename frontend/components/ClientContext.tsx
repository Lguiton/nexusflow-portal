'use client';

import React, { createContext, useContext, useState, ReactNode } from 'react';

interface ClientContextType {
  clientId: string;
  setClientId: (id: string) => void;
}

const ClientContext = createContext<ClientContextType | undefined>(undefined);

export function ClientProvider({ children }: { children: ReactNode }) {
  const [clientId, setClientId] = useState<string>('CLI-001');

  return (
    <ClientContext.Provider value={{ clientId, setClientId }}>
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
