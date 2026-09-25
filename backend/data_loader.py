import json
import os
import re
from typing import List, Dict, Any

# Resolve path to data directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTION_PATH = os.path.join(BASE_DIR, "data", "notion_mock.json")
JIRA_PATH = os.path.join(BASE_DIR, "data", "jira_mock.json")

def load_notion_data() -> List[Dict[str, Any]]:
    if not os.path.exists(NOTION_PATH):
        return []
    with open(NOTION_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_jira_data() -> List[Dict[str, Any]]:
    if not os.path.exists(JIRA_PATH):
        return []
    with open(JIRA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def search_notion(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    pages = load_notion_data()
    if not query:
        return pages[:top_k]
    
    query_tokens = set(re.findall(r'\w+', query.lower()))
    scored_pages = []
    
    for page in pages:
        text = f"{page.get('title', '')} {page.get('content', '')}".lower()
        score = 0
        for token in query_tokens:
            if len(token) > 2 and token in text:
                score += text.count(token)
                if token in page.get('title', '').lower():
                    score += 3
        
        # Default relevance score if query tokens match
        if score > 0:
            scored_pages.append((score, page))
            
    # Sort by score descending
    scored_pages.sort(key=lambda x: x[0], reverse=True)
    
    # Fallback to returning top entries if no specific keywords matched
    if not scored_pages:
        return pages[:top_k]
        
    return [p[1] for p in scored_pages[:top_k]]

def search_jira(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    tickets = load_jira_data()
    if not query:
        return tickets[:top_k]
        
    query_tokens = set(re.findall(r'\w+', query.lower()))
    scored_tickets = []
    
    for ticket in tickets:
        text = f"{ticket.get('id', '')} {ticket.get('summary', '')} {ticket.get('description', '')} {ticket.get('assignee', '')} {ticket.get('status', '')}".lower()
        score = 0
        
        # Check specific status match
        if "blocked" in query_tokens and ticket.get("status", "").lower() == "blocked":
            score += 10
        if "done" in query_tokens and ticket.get("status", "").lower() == "done":
            score += 10
            
        for token in query_tokens:
            if len(token) > 2 and token in text:
                score += text.count(token)
                if token in ticket.get('summary', '').lower():
                    score += 3
                if token in ticket.get('assignee', '').lower():
                    score += 4
                    
        if score > 0:
            scored_tickets.append((score, ticket))
            
    scored_tickets.sort(key=lambda x: x[0], reverse=True)
    
    if not scored_tickets:
        return tickets[:top_k]
        
    return [t[1] for t in scored_tickets[:top_k]]
