import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from backend.db import init_db, get_session_facts, get_session_history, clear_session
from backend.pipeline import run_agentic_rag_pipeline
from backend.data_loader import load_jira_data, load_notion_data

# Initialize database tables on app startup
init_db()

app = FastAPI(
    title="Agentic RAG over Live Data & Memory API",
    description="MVP Agentic RAG backend combining multi-step query decomposition, Jira/Notion evidence retrieval, inline citations, and SQLite memory persistence.",
    version="1.0.0"
)

# Enable CORS for local React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AskRequest(BaseModel):
    question: str = Field(..., example="What changed in Project X this quarter and what's blocked?")
    session_id: Optional[str] = Field(default="demo-session-1", example="session-abc-123")

class AskResponse(BaseModel):
    answer_text_with_citations: str
    sources_used: List[Dict[str, Any]]
    reasoning_trace: List[Dict[str, Any]]
    extracted_facts: List[str]
    session_id: str
    memory_summary: Dict[str, Any]

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": "connected (SQLite)",
        "mock_notion_count": len(load_notion_data()),
        "mock_jira_count": len(load_jira_data())
    }

@app.post("/ask", response_model=AskResponse)
def ask_question(req: AskRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    
    session_id = req.session_id or "default-session"
    result = run_agentic_rag_pipeline(session_id=session_id, question=req.question.strip())
    return result

@app.get("/sessions/{session_id}/facts")
def get_facts(session_id: str):
    facts = get_session_facts(session_id)
    return {"session_id": session_id, "facts": facts, "count": len(facts)}

@app.get("/sessions/{session_id}/history")
def get_history(session_id: str):
    history = get_session_history(session_id)
    return {"session_id": session_id, "history": history, "count": len(history)}

@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    clear_session(session_id)
    return {"status": "success", "message": f"Cleared memory for session {session_id}"}

@app.get("/sample-queries")
def get_sample_queries():
    return [
        {
            "id": "q1",
            "title": "Quarterly Changes & Blockers",
            "question": "What changed in Project X this quarter and what's blocked?"
        },
        {
            "id": "q2",
            "title": "Blocked Tasks & Owners",
            "question": "What tasks are blocked and who owns them?"
        },
        {
            "id": "q3",
            "title": "Launch Risk Summary",
            "question": "Summarize the launch risk discussion and compliance status."
        },
        {
            "id": "q4",
            "title": "Follow-up / Memory Test",
            "question": "Based on our conversation, what security and auth items need immediate attention?"
        }
    ]
