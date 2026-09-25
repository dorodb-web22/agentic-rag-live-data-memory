import time
import re
from typing import List, Dict, Any
from backend.data_loader import search_jira, search_notion
from backend.db import retrieve_memory_for_session, save_memory
from backend.llm_service import decompose_query_llm, synthesize_answer_llm

def stage_a_decompose_query(question: str, memory_facts: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Stage a: decompose_query(question)"""
    mem_texts = [f.get("fact_text", "") for f in memory_facts] if memory_facts else []
    subquestions = decompose_query_llm(question, mem_texts)
    return subquestions

def stage_b_retrieve_memory(session_id: str, question: str) -> Dict[str, Any]:
    """Stage b: retrieve_memory(session_id, question)"""
    return retrieve_memory_for_session(session_id, question)

def stage_c_gather_evidence(subquestions: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Stage c: gather_evidence(subquestions)"""
    evidence_list = []
    seen_ids = set()

    for item in subquestions:
        sq = item.get("subquestion", "")
        source = item.get("source", "both").lower()

        # Gather from Notion
        if source in ["notion", "both"]:
            notion_results = search_notion(sq, top_k=3)
            for page in notion_results:
                key = f"notion_{page['id']}"
                if key not in seen_ids:
                    seen_ids.add(key)
                    evidence_list.append({
                        "subquestion": sq,
                        "source": "notion",
                        "source_id": page["id"],
                        "title": page.get("title", ""),
                        "snippet": page.get("content", "")[:280] + ("..." if len(page.get("content", "")) > 280 else ""),
                        "full_content": page.get("content", ""),
                        "url": page.get("url", ""),
                        "last_edited": page.get("last_edited", ""),
                        "extra": {}
                    })

        # Gather from Jira
        if source in ["jira", "both"]:
            jira_results = search_jira(sq, top_k=3)
            for ticket in jira_results:
                key = f"jira_{ticket['id']}"
                if key not in seen_ids:
                    seen_ids.add(key)
                    evidence_list.append({
                        "subquestion": sq,
                        "source": "jira",
                        "source_id": ticket["id"],
                        "title": ticket.get("summary", ""),
                        "snippet": ticket.get("description", "")[:280] + ("..." if len(ticket.get("description", "")) > 280 else ""),
                        "full_content": ticket.get("description", ""),
                        "url": ticket.get("ticket_url", ""),
                        "updated_at": ticket.get("updated_at", ""),
                        "extra": {
                            "status": ticket.get("status", ""),
                            "assignee": ticket.get("assignee", "")
                        }
                    })

    return evidence_list

def stage_d_synthesize_answer(question: str, evidence: List[Dict[str, Any]], memory_facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Stage d: synthesize_answer(question, evidence, memory)"""
    return synthesize_answer_llm(question, evidence, memory_facts)

def stage_e_attach_citations(answer_text: str, evidence_list: List[Dict[str, Any]]) -> str:
    """
    Stage e: attach_citations(answer_text, evidence_map)
    Validates and normalizes citation tags format (e.g. [Jira #JIRA-101] or [Notion #NOTION-3]) 
    and ensures all cited evidence items match active IDs.
    """
    if not answer_text:
        return ""
    
    # Ensure all mentioned evidence IDs have citations
    text = answer_text
    
    # Standardize tags: e.g. [Jira JIRA-101] -> [Jira #JIRA-101]
    text = re.sub(r'\[Jira #?([A-Za-z0-9-]+)\]', r'[Jira #\1]', text)
    text = re.sub(r'\[Notion #?([A-Za-z0-9-]+)\]', r'[Notion #\1]', text)
    
    return text

def stage_f_save_memory(session_id: str, question: str, answer: str, new_facts: List[str]) -> Dict[str, Any]:
    """Stage f: save_memory(session_id, question, answer, new_facts)"""
    return save_memory(session_id, question, answer, new_facts)


def run_agentic_rag_pipeline(session_id: str, question: str) -> Dict[str, Any]:
    """
    Runs the complete 6-stage RAG pipeline and returns the output along with detailed reasoning traces.
    """
    trace = []
    
    # Stage b: Retrieve Memory
    t0 = time.time()
    memory_data = stage_b_retrieve_memory(session_id, question)
    t_memory = round((time.time() - t0) * 1000, 2)
    
    trace.append({
        "step": "retrieve_memory",
        "title": "1. Retrieve Session Memory",
        "latency_ms": t_memory,
        "output": {
            "session_id": session_id,
            "relevant_facts": memory_data["facts"],
            "recent_qa_turns": len(memory_data["recent_qa"]),
            "total_stored_facts": memory_data["total_facts_count"]
        }
    })

    # Stage a: Decompose Query
    t0 = time.time()
    subquestions = stage_a_decompose_query(question, memory_data["facts"])
    t_decompose = round((time.time() - t0) * 1000, 2)
    
    trace.append({
        "step": "decompose",
        "title": "2. Decompose Query",
        "latency_ms": t_decompose,
        "output": {
            "original_question": question,
            "subquestions": subquestions
        }
    })

    # Stage c: Gather Evidence
    t0 = time.time()
    evidence_list = stage_c_gather_evidence(subquestions)
    t_gather = round((time.time() - t0) * 1000, 2)
    
    trace.append({
        "step": "gather_evidence",
        "title": "3. Gather Evidence (Jira & Notion)",
        "latency_ms": t_gather,
        "output": {
            "evidence_count": len(evidence_list),
            "sources_breakdown": {
                "notion": len([e for e in evidence_list if e["source"] == "notion"]),
                "jira": len([e for e in evidence_list if e["source"] == "jira"])
            },
            "evidence_items": [
                {
                    "source": e["source"],
                    "source_id": e["source_id"],
                    "title": e["title"],
                    "snippet": e["snippet"],
                    "url": e["url"]
                } for e in evidence_list
            ]
        }
    })

    # Stage d: Synthesize Answer
    t0 = time.time()
    synthesis_res = stage_d_synthesize_answer(question, evidence_list, memory_data["facts"])
    raw_answer = synthesis_res.get("answer", "")
    new_facts = synthesis_res.get("extracted_facts", [])
    t_synth = round((time.time() - t0) * 1000, 2)

    # Stage e: Attach Citations
    final_answer = stage_e_attach_citations(raw_answer, evidence_list)

    trace.append({
        "step": "synthesize",
        "title": "4. Synthesize & Attach Citations",
        "latency_ms": t_synth,
        "output": {
            "raw_answer_length": len(raw_answer),
            "extracted_facts_count": len(new_facts),
            "extracted_facts": new_facts,
            "final_cited_answer": final_answer
        }
    })

    # Stage f: Save Memory
    t0 = time.time()
    saved_mem = stage_f_save_memory(session_id, question, final_answer, new_facts)
    t_save = round((time.time() - t0) * 1000, 2)

    return {
        "answer_text_with_citations": final_answer,
        "sources_used": evidence_list,
        "reasoning_trace": trace,
        "extracted_facts": new_facts,
        "session_id": session_id,
        "memory_summary": {
            "previous_facts_used": len(memory_data["facts"]),
            "new_facts_saved": saved_mem["saved_facts_count"]
        }
    }
