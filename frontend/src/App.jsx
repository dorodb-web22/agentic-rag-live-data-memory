import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { ChatInterface } from './components/ChatInterface';
import { SourceModal } from './components/SourceModal';
import { MemoryDrawer } from './components/MemoryDrawer';
import { 
  askQuestion, 
  fetchSessionFacts, 
  clearSessionMemory, 
  fetchSampleQueries, 
  checkHealth 
} from './api';

export function App() {
  const [sessionId, setSessionId] = useState('session-demo-1');
  const [messages, setMessages] = useState([]);
  const [memoryFacts, setMemoryFacts] = useState([]);
  const [sampleQueries, setSampleQueries] = useState([]);
  const [health, setHealth] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedSource, setSelectedSource] = useState(null);
  const [isMemoryOpen, setIsMemoryOpen] = useState(false);

  // Load initial backend status, sample queries, and stored facts
  useEffect(() => {
    async function init() {
      const h = await checkHealth();
      setHealth(h);

      const q = await fetchSampleQueries();
      setSampleQueries(q);

      const facts = await fetchSessionFacts(sessionId);
      setMemoryFacts(facts);
    }
    init();
  }, [sessionId]);

  const handleSendMessage = async (questionText) => {
    if (!questionText || isLoading) return;

    // Append user message
    const userMsg = { role: 'user', content: questionText };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const response = await askQuestion(questionText, sessionId);

      const assistantMsg = {
        role: 'assistant',
        content: response.answer_text_with_citations,
        sources_used: response.sources_used,
        reasoning_trace: response.reasoning_trace,
        extracted_facts: response.extracted_facts,
      };

      setMessages((prev) => [...prev, assistantMsg]);

      // Refresh memory facts list from SQLite
      const updatedFacts = await fetchSessionFacts(sessionId);
      setMemoryFacts(updatedFacts);
    } catch (error) {
      console.error("Error asking RAG pipeline:", error);
      const errorMsg = {
        role: 'assistant',
        content: `⚠️ **Error executing query:** ${error.message || 'Server error'}. Please verify backend is running on http://127.0.0.1:8000.`,
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearMemory = async () => {
    await clearSessionMemory(sessionId);
    setMessages([]);
    setMemoryFacts([]);
  };

  const handleRefreshMemory = async () => {
    const facts = await fetchSessionFacts(sessionId);
    setMemoryFacts(facts);
  };

  const handleResetSession = () => {
    const newSession = `session-${Date.now().toString().slice(-4)}`;
    setSessionId(newSession);
    setMessages([]);
    setMemoryFacts([]);
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#090d16] text-slate-100 font-sans selection:bg-indigo-500/30">
      {/* Top Navigation / Header */}
      <Header
        sessionId={sessionId}
        factCount={memoryFacts.length}
        health={health}
        onOpenMemory={() => setIsMemoryOpen(true)}
        onResetSession={handleResetSession}
      />

      {/* Main Chat Interface */}
      <main className="flex-1 flex flex-col">
        <ChatInterface
          messages={messages}
          onSendMessage={handleSendMessage}
          isLoading={isLoading}
          sampleQueries={sampleQueries}
          onSelectSource={(source) => setSelectedSource(source)}
          memoryFacts={memoryFacts}
        />
      </main>

      {/* Evidence Source Preview Modal */}
      <SourceModal
        source={selectedSource}
        onClose={() => setSelectedSource(null)}
      />

      {/* SQLite Memory Vault Drawer */}
      <MemoryDrawer
        isOpen={isMemoryOpen}
        onClose={() => setIsMemoryOpen(false)}
        facts={memoryFacts}
        onClearMemory={handleClearMemory}
        onRefreshMemory={handleRefreshMemory}
        sessionId={sessionId}
      />
    </div>
  );
}

export default App;
