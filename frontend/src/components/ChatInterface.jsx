import React, { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader2, Sparkles, AlertCircle, Database, CheckCircle2 } from 'lucide-react';
import { CitedText } from './CitationBadge';
import { ReasoningTracePanel } from './ReasoningTracePanel';
import { SampleQueries } from './SampleQueries';

export function ChatInterface({ 
  messages, 
  onSendMessage, 
  isLoading, 
  sampleQueries, 
  onSelectSource,
  memoryFacts
}) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    onSendMessage(input.trim());
    setInput('');
  };

  const handleSelectSample = (questionText) => {
    if (isLoading) return;
    onSendMessage(questionText);
  };

  return (
    <div className="flex-1 flex flex-col max-w-5xl w-full mx-auto p-4 md:p-6 pb-28">
      {/* Empty State / Welcome Screen */}
      {messages.length === 0 && (
        <div className="my-auto py-8 space-y-6 text-center animate-fadeIn">
          <div className="p-4 rounded-2xl bg-indigo-950/40 border border-indigo-500/20 max-w-xl mx-auto backdrop-blur-sm">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center mx-auto shadow-lg shadow-indigo-500/30">
              <Bot className="w-7 h-7 text-white" />
            </div>
            <h2 className="text-xl font-bold text-white mt-4 glow-text">
              Project Management RAG Assistant
            </h2>
            <p className="text-sm text-slate-300 mt-2 leading-relaxed">
              Ask any operational question about <strong>Project X</strong>. The agent will decompose your query, gather evidence from live <strong>Jira</strong> and <strong>Notion</strong> data, attach inline citations, and retain facts in SQLite memory.
            </p>

            {/* Architecture Highlights Pill */}
            <div className="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-indigo-900/40 text-left text-xs">
              <div className="p-2 rounded bg-slate-900/60 border border-slate-800">
                <span className="text-indigo-400 font-mono font-bold block">1. Decompose</span>
                <span className="text-slate-400 text-[11px]">Generates 2-4 target sub-questions</span>
              </div>
              <div className="p-2 rounded bg-slate-900/60 border border-slate-800">
                <span className="text-blue-400 font-mono font-bold block">2. Multi-RAG</span>
                <span className="text-slate-400 text-[11px]">Queries Jira tickets & Notion docs</span>
              </div>
              <div className="p-2 rounded bg-slate-900/60 border border-slate-800">
                <span className="text-purple-400 font-mono font-bold block">3. Memory</span>
                <span className="text-slate-400 text-[11px]">SQLite remembers across turns</span>
              </div>
            </div>
          </div>

          {/* Seed Queries */}
          <div className="max-w-2xl mx-auto">
            <SampleQueries
              queries={sampleQueries}
              onSelectQuery={handleSelectSample}
              disabled={isLoading}
            />
          </div>
        </div>
      )}

      {/* Message Feed */}
      <div className="space-y-6">
        {messages.map((msg, index) => (
          <div
            key={index}
            className={`flex gap-3 md:gap-4 ${
              msg.role === 'user' ? 'justify-end' : 'justify-start'
            } animate-fadeIn`}
          >
            {/* Assistant Avatar */}
            {msg.role === 'assistant' && (
              <div className="w-8 h-8 rounded-lg bg-indigo-600/30 border border-indigo-500/40 flex items-center justify-center shrink-0 mt-1">
                <Bot className="w-4 h-4 text-indigo-300" />
              </div>
            )}

            {/* Message Content Container */}
            <div className={`max-w-3xl w-full ${msg.role === 'user' ? 'max-w-lg' : ''}`}>
              {/* User Message Bubble */}
              {msg.role === 'user' ? (
                <div className="bg-indigo-600 text-white p-3.5 md:p-4 rounded-2xl rounded-tr-xs shadow-md font-medium text-sm md:text-base ml-auto">
                  {msg.content}
                </div>
              ) : (
                /* Assistant Message Card */
                <div className="glass-panel p-4 md:p-5 rounded-2xl border border-slate-800 shadow-xl space-y-3">
                  {/* Cited Answer Text */}
                  <CitedText
                    text={msg.content}
                    sources={msg.sources_used}
                    onSelectSource={onSelectSource}
                  />

                  {/* Sources Pills Summary (Quick click) */}
                  {msg.sources_used && msg.sources_used.length > 0 && (
                    <div className="pt-3 border-t border-slate-800/80 flex items-center flex-wrap gap-1.5 text-xs text-slate-400">
                      <span className="font-mono text-[11px] text-slate-400 mr-1">Sources Cited ({msg.sources_used.length}):</span>
                      {msg.sources_used.map((s, sIdx) => (
                        <button
                          key={sIdx}
                          onClick={() => onSelectSource && onSelectSource(s)}
                          className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-all hover:scale-105 ${
                            s.source === 'jira'
                              ? 'bg-blue-950/70 text-blue-300 border-blue-800/60 hover:border-blue-500'
                              : 'bg-purple-950/70 text-purple-300 border-purple-800/60 hover:border-purple-500'
                          }`}
                        >
                          {s.source === 'jira' ? 'Jira' : 'Notion'} #{s.source_id}
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Reasoning Trace Panel */}
                  {msg.reasoning_trace && (
                    <ReasoningTracePanel
                      trace={msg.reasoning_trace}
                      sources={msg.sources_used}
                      extractedFacts={msg.extracted_facts}
                      onSelectSource={onSelectSource}
                    />
                  )}
                </div>
              )}
            </div>

            {/* User Avatar */}
            {msg.role === 'user' && (
              <div className="w-8 h-8 rounded-lg bg-slate-800 border border-slate-700 flex items-center justify-center shrink-0 mt-1">
                <User className="w-4 h-4 text-slate-300" />
              </div>
            )}
          </div>
        ))}

        {/* Loading Indicator */}
        {isLoading && (
          <div className="flex gap-3 items-start animate-fadeIn">
            <div className="w-8 h-8 rounded-lg bg-indigo-600/30 border border-indigo-500/40 flex items-center justify-center shrink-0 mt-1 animate-pulse">
              <Bot className="w-4 h-4 text-indigo-300" />
            </div>
            <div className="glass-panel p-4 rounded-2xl border border-indigo-500/30 shadow-xl space-y-3 max-w-md animate-subtle-pulse">
              <div className="flex items-center gap-2 text-indigo-300 font-mono text-xs font-semibold">
                <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
                <span>Agent Orchestrator Thinking...</span>
              </div>
              <p className="text-xs text-slate-400">
                Decomposing sub-questions & querying Jira + Notion evidence tables...
              </p>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Floating Bottom Input */}
      <div className="fixed bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-[#090d16] via-[#090d16]/90 to-transparent pointer-events-none z-30">
        <div className="max-w-4xl mx-auto pointer-events-auto">
          <form onSubmit={handleSubmit} className="relative flex items-center">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isLoading}
              placeholder="Ask Project X questions (e.g., 'What changed this quarter and what is blocked?')..."
              className="w-full py-3.5 pl-4 pr-12 rounded-xl bg-slate-900/90 border border-slate-700/80 text-white placeholder-slate-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 text-sm md:text-base shadow-2xl transition-all"
            />
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              className="absolute right-2 p-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600 text-white transition-colors shadow-md"
            >
              {isLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </form>

          {/* Quick info row */}
          <div className="mt-2 flex items-center justify-between text-[11px] font-mono text-slate-400 px-1">
            <span>Press Enter to query Jira & Notion</span>
            <span>SQLite Memory: <strong className="text-indigo-400">{memoryFacts?.length || 0} facts stored</strong></span>
          </div>
        </div>
      </div>
    </div>
  );
}
