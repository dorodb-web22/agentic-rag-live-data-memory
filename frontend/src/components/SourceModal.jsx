import React from 'react';
import { X, ExternalLink, CheckSquare, Layers, Clock, User, ShieldAlert } from 'lucide-react';

export function SourceModal({ source, onClose }) {
  if (!source) return null;

  const isJira = source.source === 'jira' || (source.source_id && source.source_id.startsWith('JIRA'));
  const isNotion = source.source === 'notion' || (source.source_id && source.source_id.startsWith('NOTION'));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fadeIn">
      <div 
        className="relative w-full max-w-2xl bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh] animate-scaleUp"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className={`p-4 border-b flex items-start justify-between ${
          isJira ? 'bg-blue-950/40 border-blue-800/40' : 'bg-purple-950/40 border-purple-800/40'
        }`}>
          <div className="flex items-center gap-3">
            <div className={`p-2.5 rounded-lg border ${
              isJira ? 'bg-blue-900/50 border-blue-500/40 text-blue-400' : 'bg-purple-900/50 border-purple-500/40 text-purple-400'
            }`}>
              {isJira ? <CheckSquare className="w-6 h-6" /> : <Layers className="w-6 h-6" />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded border uppercase ${
                  isJira ? 'bg-blue-500/20 text-blue-300 border-blue-500/30' : 'bg-purple-500/20 text-purple-300 border-purple-500/30'
                }`}>
                  {isJira ? 'Jira Issue' : 'Notion Document'} #{source.source_id}
                </span>
                {source.extra?.status && (
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                    source.extra.status === 'Blocked' 
                      ? 'bg-red-500/20 text-red-300 border border-red-500/40' 
                      : source.extra.status === 'Done'
                      ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                      : 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                  }`}>
                    {source.extra.status}
                  </span>
                )}
              </div>
              <h3 className="text-lg font-semibold text-slate-100 mt-1">
                {source.title || 'Untitled Document'}
              </h3>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body Content */}
        <div className="p-5 space-y-4 overflow-y-auto">
          {/* Metadata Grid */}
          <div className="grid grid-cols-2 gap-3 p-3 bg-slate-950/50 rounded-lg border border-slate-800 text-xs text-slate-300">
            {source.extra?.assignee && (
              <div className="flex items-center gap-2">
                <User className="w-4 h-4 text-slate-400" />
                <span className="text-slate-400">Assignee:</span>
                <span className="font-medium text-slate-100">{source.extra.assignee}</span>
              </div>
            )}
            {source.updated_at && (
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-slate-400" />
                <span className="text-slate-400">Updated:</span>
                <span className="font-mono text-slate-300">{new Date(source.updated_at).toLocaleDateString()}</span>
              </div>
            )}
            {source.last_edited && (
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-slate-400" />
                <span className="text-slate-400">Last Edited:</span>
                <span className="font-mono text-slate-300">{new Date(source.last_edited).toLocaleDateString()}</span>
              </div>
            )}
            {source.subquestion && (
              <div className="col-span-2 flex items-start gap-2 pt-1 border-t border-slate-800/60">
                <ShieldAlert className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                <span><strong className="text-indigo-300">Retrieved for Sub-question:</strong> {source.subquestion}</span>
              </div>
            )}
          </div>

          {/* Snippet / Full Text */}
          <div>
            <h4 className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-400 mb-2">
              Content & Evidence Snippet
            </h4>
            <div className="p-4 bg-slate-950/80 rounded-lg border border-slate-800/80 text-sm text-slate-200 font-sans leading-relaxed whitespace-pre-wrap">
              {source.full_content || source.snippet || 'No text content available.'}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950 flex items-center justify-between">
          <span className="text-xs text-slate-400">
            Mocked operational database item
          </span>
          <div className="flex items-center gap-2">
            <a
              href={source.url || '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors shadow-sm"
              onClick={(e) => {
                if (!source.url || source.url === '#') e.preventDefault();
              }}
            >
              <span>View in {isJira ? 'Jira' : 'Notion'}</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
