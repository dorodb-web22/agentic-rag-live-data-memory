import React from 'react';
import { Database, Trash2, X, RefreshCw, CheckCircle2, Clock, BrainCircuit } from 'lucide-react';

export function MemoryDrawer({ isOpen, onClose, facts, onClearMemory, onRefreshMemory, sessionId }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-xs animate-fadeIn">
      <div className="w-full max-w-md bg-slate-900 border-l border-slate-700/80 h-full flex flex-col shadow-2xl animate-slideLeft">
        {/* Header */}
        <div className="p-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              <BrainCircuit className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
                <span>SQLite Memory Vault</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800">
                  {facts?.length || 0} Facts
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Session ID: <code className="text-indigo-300 font-mono">{sessionId}</code>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Note on SQLite Architecture */}
        <div className="p-3 bg-indigo-950/40 border-b border-indigo-900/30 text-xs text-indigo-200/90 leading-relaxed flex items-start gap-2">
          <Database className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
          <span>
            <strong>Cross-session Persistence:</strong> Facts are automatically extracted by Claude and saved to local SQLite tables (<code>facts</code>, <code>qa_history</code>). In the full PRD, this is vector-indexed with Chroma/Pinecone.
          </span>
        </div>

        {/* Content list */}
        <div className="flex-1 p-4 overflow-y-auto space-y-3">
          {facts && facts.length > 0 ? (
            facts.map((item, idx) => (
              <div 
                key={item.id || idx}
                className="p-3 rounded-lg bg-slate-950/80 border border-slate-800/90 space-y-1.5 transition-all hover:border-indigo-500/30 shadow-sm"
              >
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                  <p className="text-xs text-slate-200 leading-normal font-sans">
                    {item.fact_text}
                  </p>
                </div>
                {item.created_at && (
                  <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 pt-1 border-t border-slate-800/60">
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3 text-slate-400" />
                      {new Date(item.created_at).toLocaleTimeString()}
                    </span>
                    <span>Fact #{item.id}</span>
                  </div>
                )}
              </div>
            ))
          ) : (
            <div className="py-12 text-center text-slate-400 space-y-3">
              <Database className="w-10 h-10 mx-auto text-slate-700" />
              <p className="text-sm">No facts stored in SQLite yet for this session.</p>
              <p className="text-xs text-slate-400 max-w-xs mx-auto">
                Ask a question in the chat, and the agent will automatically extract and persist key facts here.
              </p>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div className="p-4 bg-slate-950 border-t border-slate-800 flex items-center justify-between">
          <button
            onClick={onRefreshMemory}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>

          <button
            onClick={onClearMemory}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-950/80 hover:bg-red-900 text-red-300 border border-red-800/60 text-xs font-medium transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Reset Memory</span>
          </button>
        </div>
      </div>
    </div>
  );
}
