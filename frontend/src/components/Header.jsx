import React from 'react';
import { BrainCircuit, Database, RefreshCw, Sparkles, Layers, CheckSquare, ShieldCheck, Activity } from 'lucide-react';

export function Header({ 
  sessionId, 
  factCount, 
  health, 
  onOpenMemory, 
  onResetSession 
}) {
  const isHealthy = health?.status === 'healthy';

  return (
    <header className="sticky top-0 z-40 w-full glass-panel border-b border-slate-800 shadow-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        {/* Branding */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-br from-indigo-600 to-purple-600 text-white shadow-lg shadow-indigo-500/20">
            <BrainCircuit className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold tracking-tight text-white glow-text">
                Agentic RAG
              </h1>
              <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-700/60">
                MVP Demo
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Live Data Synthesis (Jira & Notion) + Cross-Session Memory
            </p>
          </div>
        </div>

        {/* Status Indicators & Memory Actions */}
        <div className="flex items-center flex-wrap gap-2.5">
          {/* Health Badge */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300">
            <Activity className={`w-3.5 h-3.5 ${isHealthy ? 'text-emerald-400' : 'text-amber-400'}`} />
            <span className="font-mono text-[11px]">{isHealthy ? 'Backend Connected' : 'Offline / Standby'}</span>
          </div>

          {/* Sources Badge */}
          <div className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300">
            <span className="flex items-center gap-1 text-blue-400">
              <CheckSquare className="w-3.5 h-3.5" /> Jira
            </span>
            <span className="text-slate-600">•</span>
            <span className="flex items-center gap-1 text-purple-400">
              <Layers className="w-3.5 h-3.5" /> Notion
            </span>
          </div>

          {/* Memory Vault Button */}
          <button
            onClick={onOpenMemory}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-indigo-950/80 hover:bg-indigo-900/90 text-indigo-200 border border-indigo-700/60 text-xs font-medium transition-all duration-200 shadow-sm hover:scale-[1.02]"
          >
            <Database className="w-3.5 h-3.5 text-indigo-400" />
            <span>SQLite Memory</span>
            <span className="px-1.5 py-0.2 rounded-full bg-indigo-500 text-white font-mono text-[10px] font-bold">
              {factCount}
            </span>
          </button>

          {/* Reset Session Button */}
          <button
            onClick={onResetSession}
            title="Reset active chat session and memory"
            className="p-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
