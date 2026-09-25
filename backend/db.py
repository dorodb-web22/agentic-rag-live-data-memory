import sqlite3
import os
import re
from datetime import datetime
from typing import List, Dict, Any

# SQLite DB Path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "memory.db")

"""
ARCHITECTURE NOTE (MVP Placeholder):
This SQLite implementation uses relational tables (sessions, qa_history, facts) 
and simple keyword matching for memory retrieval.
In a production deployment, this layer would be swapped with a hybrid vector storage solution 
(e.g., ChromaDB, Pinecone, or pgvector) for semantic vector similarity search 
and episodic context retrieval as outlined in the PRD.
"""

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL
    )
    """)
    
    # QA History table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qa_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(session_id)
    )
    """)
    
    # Facts table (extracted facts across sessions/turns)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        fact_text TEXT NOT NULL,
        source_qa_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(session_id),
        FOREIGN KEY (source_qa_id) REFERENCES qa_history(id)
    )
    """)
    
    conn.commit()
    conn.close()

def ensure_session(session_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,))
    if not cursor.fetchone():
        now = datetime.utcnow().isoformat()
        cursor.execute("INSERT INTO sessions (session_id, created_at) VALUES (?, ?)", (session_id, now))
        conn.commit()
    conn.close()

def retrieve_memory_for_session(session_id: str, question: str) -> Dict[str, Any]:
    ensure_session(session_id)
    conn = get_db()
    cursor = conn.cursor()
    
    # Fetch all stored facts for this session
    cursor.execute("SELECT id, fact_text, created_at FROM facts WHERE session_id = ? ORDER BY id DESC", (session_id,))
    all_facts = [dict(row) for row in cursor.fetchall()]
    
    # Fetch recent QA history
    cursor.execute("SELECT id, question, answer, created_at FROM qa_history WHERE session_id = ? ORDER BY id DESC LIMIT 5", (session_id,))
    recent_qa = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    # Keyword relevance filter on facts
    relevant_facts = []
    if question and all_facts:
        q_tokens = set(re.findall(r'\w+', question.lower()))
        for fact in all_facts:
            f_text = fact["fact_text"].lower()
            if any(tok in f_text for tok in q_tokens if len(tok) > 3):
                relevant_facts.append(fact)
                
    # If no specific keyword matches, return the 5 most recent facts as active session context
    if not relevant_facts:
        relevant_facts = all_facts[:5]
        
    return {
        "session_id": session_id,
        "facts": relevant_facts,
        "recent_qa": recent_qa,
        "total_facts_count": len(all_facts)
    }

def save_memory(session_id: str, question: str, answer: str, facts_list: List[str]) -> Dict[str, Any]:
    ensure_session(session_id)
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    
    # Save QA turn
    cursor.execute(
        "INSERT INTO qa_history (session_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
        (session_id, question, answer, now)
    )
    qa_id = cursor.lastrowid
    
    # Save extracted facts
    inserted_facts = []
    for fact in facts_list:
        fact_str = fact.strip()
        if fact_str:
            cursor.execute(
                "INSERT INTO facts (session_id, fact_text, source_qa_id, created_at) VALUES (?, ?, ?, ?)",
                (session_id, fact_str, qa_id, now)
            )
            inserted_facts.append({"id": cursor.lastrowid, "fact_text": fact_str, "created_at": now})
            
    conn.commit()
    conn.close()
    
    return {
        "qa_id": qa_id,
        "saved_facts_count": len(inserted_facts),
        "facts": inserted_facts
    }

def get_session_facts(session_id: str) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, fact_text, source_qa_id, created_at FROM facts WHERE session_id = ? ORDER BY id DESC", (session_id,))
    facts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return facts

def get_session_history(session_id: str) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, question, answer, created_at FROM qa_history WHERE session_id = ? ORDER BY id ASC", (session_id,))
    history = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return history

def clear_session(session_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM facts WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM qa_history WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
