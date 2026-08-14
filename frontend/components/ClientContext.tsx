'use client';

import React, { createContext, useContext, useState, ReactNode } from 'react';

// Define the shape of our context
interface ClientContextType {
  clientId: string;
  setClientId: (id: string) => void;
}

// Create the actual context
const ClientContext = createContext<ClientContextType | undefined>(undefined);

// The Provider that wraps your app and holds the state
export function ClientProvider({ children }: { children: ReactNode }) {
  // Defaulting to CLI-001 so it matches Claude's testing plan
  const [clientId, setClientId] = useState<string>('CLI-001'); 

  return (
    <ClientContext.Provider value={{ clientId, setClientId }}>
      {children}
    </ClientContext.Provider>
  );
}

// The Hook that Dropzone and SearchBar use to access the ID
export function useClientId() {
  const context = useContext(ClientContext);
  if (context === undefined) {
    throw new Error('useClientId must be used within a ClientProvider');
  }
  return context;
}

// The UI dropdown menu you will put in your header to switch clients
export function ClientSwitcher() {
  const { clientId, setClientId } = useClientId();

  return (
    <div className="flex items-center gap-2 bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-800">
      <label className="text-xs font-medium text-slate-400">Active Tenant:</label>
      <select
        value={clientId}
        onChange={(e) => setClientId(e.target.value)}
        className="bg-slate-950 border border-slate-700 text-cyan-400 text-xs px-2 py-1 rounded focus:outline-none focus:border-cyan-500 font-mono cursor-pointer"
      >
        <option value="CLI-001">CLI-001 (Client A)</option>
        <option value="CLI-002">CLI-002 (Client B)</option>
        <option value="CLI-003">CLI-003 (Client C)</option>
        <option value="HACKER-99">HACKER-99 (Unauthorized)</option>
      </select>
    </div>
  );
}