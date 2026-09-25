import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Terminal, Cpu, Database, FileText, Sparkles, CheckCircle2, Clock } from 'lucide-react';

export function ReasoningTracePanel({ trace, sources, extractedFacts, onSelectSource }) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState(0);

  if (!trace || trace.length === 0) return null;

  const totalLatency = trace.reduce((acc, curr) => acc + (curr.latency_ms || 0), 0).toFixed(1);

  return (
    <div className="mt-4 border border-indigo-500/20 rounded-xl bg-slate-950/70 overflow-hidden shadow-lg transition-all duration-200">
      {/* Trace Header / Toggle */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-4 py-3 bg-slate-900/90 hover:bg-slate-800/80 flex items-center justify-between transition-colors border-b border-indigo-500/10"
      >
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Cpu className="w-4 h-4" />
          </div>
          <div className="text-left">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono font-semibold uppercase tracking-wider text-indigo-300">
                Agent Reasoning Trace
              </span>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-indigo-950/80 text-indigo-300 border border-indigo-800/50">
                4 Pipeline Steps
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Decomposed sub-questions • Multi-source RAG • SQLite memory
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs font-mono text-slate-400 bg-slate-950/80 px-2.5 py-1 rounded-md border border-slate-800">
            <Clock className="w-3.5 h-3.5 text-indigo-400" />
            <span>{totalLatency}ms</span>
          </div>
          {isOpen ? (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-400" />
          )}
        </div>
      </button>

      {/* Expanded Trace Body */}
      {isOpen && (
        <div className="p-4 space-y-4">
          {/* Step Selector Tabs */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 border-b border-slate-800 pb-3">
            {trace.map((stepItem, idx) => {
              const icons = [Database, Terminal, FileText, Sparkles];
              const StepIcon = icons[idx % icons.length];
              const isActive = activeTab === idx;

              return (
                <button
                  key={idx}
                  onClick={() => setActiveTab(idx)}
                  className={`p-2.5 rounded-lg border text-left transition-all flex items-start gap-2 ${
                    isActive
                      ? 'bg-indigo-950/70 border-indigo-500/50 text-indigo-200 shadow-sm'
                      : 'bg-slate-900/40 border-slate-800/80 text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                  }`}
                >
                  <StepIcon className={`w-4 h-4 mt-0.5 shrink-0 ${isActive ? 'text-indigo-400' : 'text-slate-500'}`} />
                  <div className="overflow-hidden">
                    <div className="text-xs font-semibold truncate">{stepItem.title}</div>
                    <div className="text-[10px] font-mono text-slate-400 mt-0.5">{stepItem.latency_ms}ms</div>
                  </div>
                </button>
              );
            })}
          </div>

          {/* Active Step Content */}
          {trace[activeTab] && (
            <div className="bg-slate-900/90 rounded-lg border border-slate-800 p-4 space-y-3">
              <div className="flex items-center justify-between text-xs text-indigo-300 font-mono">
                <span className="font-semibold uppercase tracking-wider">{trace[activeTab].title}</span>
                <span>Latency: {trace[activeTab].latency_ms}ms</span>
              </div>

              {/* Step 0: Memory Retrieval */}
              {trace[activeTab].step === 'retrieve_memory' && (
                <div className="space-y-2 text-xs">
                  <p className="text-slate-300">
                    Retrieved SQLite memory facts for session <code className="text-indigo-300 bg-slate-950 px-1 py-0.5 rounded">{trace[activeTab].output.session_id}</code>:
                  </p>
                  {trace[activeTab].output.relevant_facts?.length > 0 ? (
                    <div className="space-y-1.5">
                      {trace[activeTab].output.relevant_facts.map((fact, fIdx) => (
                        <div key={fIdx} className="p-2 rounded bg-slate-950 border border-indigo-900/30 flex items-start gap-2 text-slate-200">
                          <CheckCircle2 className="w-3.5 h-3.5 text-indigo-400 shrink-0 mt-0.5" />
                          <span>{fact.fact_text}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-2.5 rounded bg-slate-950 text-slate-400 italic">
                      No prior facts matched in memory for this initial query turn. Memory will be populated after synthesis.
                    </div>
                  )}
                </div>
              )}

              {/* Step 1: Query Decomposition */}
              {trace[activeTab].step === 'decompose' && (
                <div className="space-y-2 text-xs">
                  <p className="text-slate-300">
                    Decomposed primary question into sub-questions targeted at specific data sources:
                  </p>
                  <div className="space-y-2">
                    {trace[activeTab].output.subquestions?.map((sq, sqIdx) => (
                      <div key={sqIdx} className="p-2.5 bg-slate-950 rounded border border-slate-800 flex items-center justify-between gap-3">
                        <span className="text-slate-200 font-medium">"{sq.subquestion}"</span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                          sq.source === 'jira' ? 'bg-blue-950 text-blue-300 border border-blue-800' :
                          sq.source === 'notion' ? 'bg-purple-950 text-purple-300 border border-purple-800' :
                          'bg-indigo-950 text-indigo-300 border border-indigo-800'
                        }`}>
                          Target: {sq.source}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Step 2: Gather Evidence */}
              {trace[activeTab].step === 'gather_evidence' && (
                <div className="space-y-2 text-xs">
                  <div className="flex items-center gap-3 text-slate-300">
                    <span>Retrieved <strong>{trace[activeTab].output.evidence_count}</strong> evidence items</span>
                    <span className="text-blue-400 font-mono">Jira: {trace[activeTab].output.sources_breakdown?.jira}</span>
                    <span className="text-purple-400 font-mono">Notion: {trace[activeTab].output.sources_breakdown?.notion}</span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2 max-h-60 overflow-y-auto">
                    {sources?.map((item, itemIdx) => (
                      <div 
                        key={itemIdx}
                        onClick={() => onSelectSource && onSelectSource(item)}
                        className={`p-2.5 rounded-lg border text-left cursor-pointer transition-all hover:scale-[1.01] ${
                          item.source === 'jira' 
                            ? 'bg-blue-950/40 border-blue-800/50 hover:bg-blue-900/50' 
                            : 'bg-purple-950/40 border-purple-800/50 hover:bg-purple-900/50'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className={`font-mono text-[10px] font-bold px-1.5 py-0.5 rounded ${
                            item.source === 'jira' ? 'bg-blue-500/20 text-blue-300' : 'bg-purple-500/20 text-purple-300'
                          }`}>
                            {item.source === 'jira' ? 'Jira' : 'Notion'} #{item.source_id}
                          </span>
                          <span className="text-[10px] text-slate-400 underline">View details</span>
                        </div>
                        <h5 className="font-semibold text-slate-200 mt-1 truncate">{item.title}</h5>
                        <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">{item.snippet}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Step 3: Synthesis & Citations */}
              {trace[activeTab].step === 'synthesize' && (
                <div className="space-y-2 text-xs">
                  <p className="text-slate-300">
                    Synthesized answer and extracted new facts for SQLite persistence:
                  </p>
                  {extractedFacts?.length > 0 && (
                    <div className="p-3 bg-slate-950 rounded border border-indigo-900/40 space-y-1">
                      <div className="text-[11px] font-semibold text-indigo-300 uppercase tracking-wider">
                        Extracted Facts (Saved to SQLite):
                      </div>
                      {extractedFacts.map((factStr, fIdx) => (
                        <div key={fIdx} className="text-slate-200 flex items-start gap-2 pt-1">
                          <span className="text-indigo-400">•</span>
                          <span>{factStr}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Raw JSON inspect button */}
              <details className="mt-3 pt-2 border-t border-slate-800/80">
                <summary className="text-[10px] font-mono text-slate-500 cursor-pointer hover:text-slate-300">
                  Inspect Raw Step Output JSON
                </summary>
                <pre className="mt-2 p-2.5 bg-slate-950 rounded border border-slate-800 text-[10px] font-mono text-emerald-400 overflow-x-auto">
                  {JSON.stringify(trace[activeTab].output, null, 2)}
                </pre>
              </details>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
