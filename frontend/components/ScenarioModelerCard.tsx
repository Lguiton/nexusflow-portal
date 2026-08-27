'use client';

import React, { useState } from 'react';
import { Sliders, TrendingUp, UserPlus, UserMinus, Loader2, AlertCircle, ChevronRight, Clock } from 'lucide-react';
import { useClientId } from './ClientContext';

interface ScenarioFigures {
  monthly_revenue: number;
  monthly_expense: number;
  monthly_net: number;
  cash_runway_months: number | null;
}

interface ScenarioPayload {
  agent: string;
  status: 'COMPLETED' | 'NO_DATA' | 'ERROR';
  scenario_type?: string;
  amount?: number;
  assumed_cash_reserves?: number;
  baseline?: ScenarioFigures;
  projected?: ScenarioFigures;
  runway_delta_months?: number | null;
  insights?: string[];
}

const SCENARIO_OPTIONS: { value: string; label: string; amountLabel: string; icon: React.ReactNode }[] = [
  { value: 'price_change_pct', label: 'Price Change', amountLabel: 'Price change (%, +/-)', icon: <TrendingUp className="w-3.5 h-3.5" /> },
  { value: 'new_hire_monthly_cost', label: 'New Hire', amountLabel: 'Monthly cost ($)', icon: <UserPlus className="w-3.5 h-3.5" /> },
  { value: 'churned_account_monthly_revenue', label: 'Churned Account', amountLabel: 'Monthly revenue lost ($)', icon: <UserMinus className="w-3.5 h-3.5" /> },
];

const currency = (n: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);

export default function ScenarioModelerCard() {
  const [scenarioType, setScenarioType] = useState<string>('price_change_pct');
  const [amount, setAmount] = useState<string>('');
  const [cashReserves, setCashReserves] = useState<string>('');
  const [data, setData] = useState<ScenarioPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  let currentClientId = 'default_client';
  let authToken: string | null = null;
  try {
    const clientCtx = useClientId() as any;
    if (clientCtx && clientCtx.clientId) {
      currentClientId = clientCtx.clientId;
    }
    authToken = clientCtx?.authToken ?? null;
  } catch (e) {}

  const selected = SCENARIO_OPTIONS.find((o) => o.value === scenarioType) || SCENARIO_OPTIONS[0];

  async function handleRun() {
    const parsedAmount = parseFloat(amount);
    if (Number.isNaN(parsedAmount)) {
      setError('Enter a numeric amount first.');
      return;
    }
    const parsedReserves = cashReserves.trim() === '' ? undefined : parseFloat(cashReserves);
    if (cashReserves.trim() !== '' && (Number.isNaN(parsedReserves) || (parsedReserves as number) < 0)) {
      setError('Cash reserves override must be a non-negative number.');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';
      const authHeaders: Record<string, string> = authToken ? { Authorization: `Bearer ${authToken}` } : {};

      const response = await fetch(`${backendUrl}/api/v1/predictive/scenario`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-client-id': currentClientId,
          ...authHeaders,
        },
        body: JSON.stringify({
          scenario_type: scenarioType,
          amount: parsedAmount,
          ...(parsedReserves !== undefined ? { cash_reserves: parsedReserves } : {}),
        }),
      });

      if (!response.ok) {
        let detail = `Server status: ${response.status}`;
        try {
          const errBody = await response.json();
          if (errBody?.detail) detail = errBody.detail;
        } catch (e) {}
        throw new Error(detail);
      }

      const result: ScenarioPayload = await response.json();
      setData(result);
    } catch (err: any) {
      console.error('Scenario Modeler fetch failed:', err);
      setError(err.message || 'Scenario modeling failed. Please try again.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  const netDelta =
    data?.status === 'COMPLETED' && data.baseline && data.projected
      ? Math.round((data.projected.monthly_net - data.baseline.monthly_net) * 100) / 100
      : null;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg flex flex-col">
      <div className="bg-slate-950/50 border-b border-slate-800 p-5 flex items-center gap-3">
        <div className="p-2 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <Sliders className="w-5 h-5 text-amber-400" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-white">Scenario Modeler</h2>
          <p className="text-xs text-slate-400">What-if runway &amp; cash-flow simulator</p>
        </div>
      </div>

      <div className="p-6 flex-1 space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {SCENARIO_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setScenarioType(opt.value)}
              className={`flex items-center justify-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border transition-colors ${
                scenarioType === opt.value
                  ? 'bg-amber-500/10 border-amber-500/40 text-amber-300'
                  : 'bg-slate-950/50 border-slate-800 text-slate-400 hover:border-slate-700'
              }`}
            >
              {opt.icon}
              {opt.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
              {selected.amountLabel}
            </label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={scenarioType === 'price_change_pct' ? 'e.g. 10 or -5' : 'e.g. 6000'}
              className="w-full bg-slate-950/50 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-amber-500/50"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
              Cash reserves override (optional)
            </label>
            <input
              type="number"
              value={cashReserves}
              onChange={(e) => setCashReserves(e.target.value)}
              placeholder="Uses assumed platform reserve"
              className="w-full bg-slate-950/50 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-amber-500/50"
            />
          </div>
        </div>

        <button
          onClick={handleRun}
          disabled={loading || amount.trim() === ''}
          className="w-full bg-amber-600 hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm px-4 py-2.5 rounded-lg flex items-center justify-center gap-2 transition-colors"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sliders className="w-4 h-4" />}
          Run Scenario
        </button>

        {error && (
          <div className="flex items-start gap-2 bg-rose-500/10 border border-rose-500/20 rounded-lg p-3">
            <AlertCircle className="w-4 h-4 text-rose-400 mt-0.5 shrink-0" />
            <p className="text-sm text-rose-300">{error}</p>
          </div>
        )}

        {data?.status === 'NO_DATA' && (
          <div className="text-center py-6 text-sm text-slate-500">
            No ledger data has been ingested yet — upload a CSV ledger before running a what-if scenario.
          </div>
        )}

        {data?.status === 'COMPLETED' && data.baseline && data.projected && (
          <div className="space-y-5 animate-in fade-in duration-500">
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-4">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Baseline (latest month)</span>
                <div className="mt-2 space-y-1.5 text-sm">
                  <div className="flex justify-between"><span className="text-slate-500">Revenue</span><span className="text-slate-200">{currency(data.baseline.monthly_revenue)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">Expense</span><span className="text-slate-200">{currency(data.baseline.monthly_expense)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">Net</span><span className="text-slate-200">{currency(data.baseline.monthly_net)}</span></div>
                  <div className="flex justify-between items-center pt-1 border-t border-slate-800/80">
                    <span className="text-slate-500 flex items-center gap-1"><Clock className="w-3 h-3" />Runway</span>
                    <span className="text-slate-200">{data.baseline.cash_runway_months !== null ? `${data.baseline.cash_runway_months.toFixed(1)} mo` : 'not burn-limited'}</span>
                  </div>
                </div>
              </div>
              <div className="bg-slate-950/50 border border-amber-500/30 rounded-xl p-4">
                <span className="text-xs font-semibold uppercase tracking-wider text-amber-400">Projected</span>
                <div className="mt-2 space-y-1.5 text-sm">
                  <div className="flex justify-between"><span className="text-slate-500">Revenue</span><span className="text-slate-100">{currency(data.projected.monthly_revenue)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">Expense</span><span className="text-slate-100">{currency(data.projected.monthly_expense)}</span></div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Net</span>
                    <span className={netDelta !== null && netDelta < 0 ? 'text-rose-400 font-semibold' : netDelta !== null && netDelta > 0 ? 'text-emerald-400 font-semibold' : 'text-slate-100'}>
                      {currency(data.projected.monthly_net)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center pt-1 border-t border-slate-800/80">
                    <span className="text-slate-500 flex items-center gap-1"><Clock className="w-3 h-3" />Runway</span>
                    <span className="text-slate-100">{data.projected.cash_runway_months !== null ? `${data.projected.cash_runway_months.toFixed(1)} mo` : 'not burn-limited'}</span>
                  </div>
                </div>
              </div>
            </div>

            {data.insights && data.insights.length > 0 && (
              <div className="space-y-3">
                {data.insights.map((insight, idx) => (
                  <div key={idx} className="flex gap-3 items-start bg-slate-800/30 p-3.5 rounded-lg border border-slate-700/30">
                    <ChevronRight className="w-4 h-4 text-amber-500 mt-0.5 shrink-0" />
                    <p className={idx === data.insights!.length - 1 ? 'text-xs text-slate-500 italic leading-relaxed' : 'text-sm text-slate-300 leading-relaxed'}>
                      {insight}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
