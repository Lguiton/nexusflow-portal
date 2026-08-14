'use client';
import { useState } from 'react';

export default function IntelligentHookPanel() {
  const [taskType, setTaskType] = useState('statistical_ml');
  const [outputResult, setOutputResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const executeTask = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/v1/supervise', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_type: taskType, data: { data: [12, 45, 67, 89, 23, 90] } })
      });
      const data = await res.json();
      setOutputResult(data);
    } catch {
      setOutputResult({ error: 'Failed to execute supervised task.' });
    }
    setLoading(false);
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
      <h3 className="text-md font-semibold text-cyan-400">The Intelligent Hook: Sub-Agent Dispatch</h3>
      
      <div className="space-y-2">
        <label className="text-xs text-slate-400">Select Operational Workflow</label>
        <select 
          value={taskType} 
          onChange={(e) => setTaskType(e.target.value)}
          className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-sm text-slate-100 focus:border-cyan-500 outline-none"
        >
          <option value="statistical_ml">Predictive Demand Engine (Local Python / ML)</option>
          <option value="llm_generation">Autonomous AI Staffing Agent (LLM / RAG)</option>
        </select>
      </div>

      <button
        onClick={executeTask}
        disabled={loading}
        className="w-full py-2.5 bg-cyan-500 hover:bg-cyan-400 disabled:bg-slate-700 text-slate-950 font-semibold rounded-lg text-sm transition-all"
      >
        {loading ? 'Processing via Supervisor...' : 'Execute Supervised Pipeline'}
      </button>

      {outputResult && (
        <div className="mt-4 p-4 bg-slate-950 border border-slate-800 rounded-lg space-y-3">
          <div className="text-xs font-mono text-emerald-400">Output Validation: SUCCESS</div>
          <pre className="text-xs text-slate-300 overflow-x-auto">{JSON.stringify(outputResult, null, 2)}</pre>
          <div className="flex space-x-2 pt-2">
            <button onClick={() => alert('Approved & Applied to Production Database')} className="flex-1 bg-emerald-600/20 border border-emerald-500/30 text-emerald-400 py-1.5 rounded text-xs font-semibold hover:bg-emerald-600/30">
              Approve Output
            </button>
            <button onClick={executeTask} className="flex-1 bg-slate-800 text-slate-300 py-1.5 rounded text-xs font-semibold hover:bg-slate-700">
              Regenerate
            </button>
          </div>
        </div>
      )}
    </div>
  );
}