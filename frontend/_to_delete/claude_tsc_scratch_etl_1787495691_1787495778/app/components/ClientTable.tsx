'use client';

import React, { useState, useEffect } from 'react';

export default function ClientTable() {
  const [clients, setClients] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("http://localhost:8000/api/v1/clients")
      .then(res => res.json())
      .then(data => {
        setClients(data);
        setLoading(false);
      })
      .catch(err => {
        console.error("Failed to fetch clients", err);
        setLoading(false);
      });
  }, []);

  return (
    <div className="w-full bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-md text-slate-100 mt-6">
      <div className="mb-4 border-b border-slate-800 pb-3">
        <h3 className="text-lg font-bold text-white">Client Directory</h3>
        <p className="text-xs text-slate-400 mt-0.5">Active and historical organization records.</p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-950 text-slate-400 border-b border-slate-800">
            <tr>
              <th className="p-3 font-semibold">Client ID</th>
              <th className="p-3 font-semibold">Status</th>
              <th className="p-3 font-semibold">MRR</th>
              <th className="p-3 font-semibold">Signup Date</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {loading ? (
              <tr>
                <td colSpan={4} className="p-4 text-center text-slate-500">
                  Loading records...
                </td>
              </tr>
            ) : clients.length === 0 ? (
              <tr>
                <td colSpan={4} className="p-4 text-center text-slate-500">
                  No clients found.
                </td>
              </tr>
            ) : (
              clients.map((client, idx) => (
                <tr key={idx} className="hover:bg-slate-800/50 transition-colors">
                  <td className="p-3 font-mono text-xs text-indigo-400">{client.client_id}</td>
                  <td className="p-3">
                    <span className="px-2 py-1 rounded text-xs font-semibold bg-emerald-950 text-emerald-400">
                      {client.status || 'Active'}
                    </span>
                  </td>
                  <td className="p-3 font-mono text-emerald-400">
                    ${client.mrr?.toLocaleString() || '0'}
                  </td>
                  <td className="p-3 text-slate-400 text-xs">{client.signup_date}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}