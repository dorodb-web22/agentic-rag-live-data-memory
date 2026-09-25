import React from 'react';
import { Sparkles, HelpCircle } from 'lucide-react';

export function SampleQueries({ queries, onSelectQuery, disabled }) {
  if (!queries || queries.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-mono font-medium text-slate-400">
        <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
        <span>Try Seed Demo Questions:</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {queries.map((q) => (
          <button
            key={q.id}
            disabled={disabled}
            onClick={() => onSelectQuery(q.question)}
            className="p-3 text-left rounded-xl bg-slate-900/60 hover:bg-slate-800/80 border border-slate-800 hover:border-indigo-500/40 text-slate-200 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed group shadow-sm"
          >
            <div className="text-xs font-semibold text-indigo-300 group-hover:text-indigo-200 transition-colors flex items-center justify-between">
              <span>{q.title}</span>
              <HelpCircle className="w-3.5 h-3.5 text-slate-500 group-hover:text-indigo-400" />
            </div>
            <p className="text-xs text-slate-400 mt-1 line-clamp-1">
              "{q.question}"
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
