import os
import json
import logging
from typing import List, Dict, Any

# Load dotenv if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("agentic_rag")

def get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or api_key.strip() == "" or api_key == "your_anthropic_api_key_here":
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        logger.warning(f"Failed to initialize Anthropic client: {e}")
        return None

def decompose_query_llm(question: str, memory_context: List[str] = None) -> List[Dict[str, str]]:
    """
    Calls LLM to break question down into 2-4 target sub-questions, each tagged with 'jira', 'notion', or 'both'.
    """
    client = get_anthropic_client()
    
    if client:
        try:
            mem_text = "\n".join([f"- {m}" for m in (memory_context or [])])
            prompt = f"""You are an Agentic RAG query planner for Project X.
Given the user's question and past session memory, decompose the question into 2 to 4 clear, specific sub-questions.
Each sub-question must specify its target source: "jira" (for ticket status, assignees, tasks), "notion" (for docs, architecture, meeting notes, risks), or "both".

User Question: "{question}"
Past Session Memory:
{mem_text if mem_text else "None"}

Return strictly a JSON list of objects with fields "subquestion" and "source".
Example:
[
  {{"subquestion": "What architecture changes occurred in Project X recently?", "source": "notion"}},
  {{"subquestion": "Which Jira tickets are currently in Blocked status and who is assigned?", "source": "jira"}}
]
"""
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=500,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}]
            )
            content = response.content[0].text
            # Extract JSON from codeblocks if wrapped
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            parsed = json.loads(content)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed
        except Exception as e:
            logger.error(f"Error in LLM decompose: {e}")

    # Heuristic Fallback Planner (if API key missing or call fails)
    q_lower = question.lower()
    subquestions = []
    
    if "blocked" in q_lower or "task" in q_lower or "ticket" in q_lower or "who" in q_lower:
        subquestions.append({
            "subquestion": "What tickets or tasks are currently blocked or in progress in Jira?",
            "source": "jira"
        })
    if "change" in q_lower or "quarter" in q_lower or "architecture" in q_lower or "roadmap" in q_lower:
        subquestions.append({
            "subquestion": "What major architecture, roadmap, or quarterly changes were documented in Notion?",
            "source": "notion"
        })
    if "risk" in q_lower or "launch" in q_lower or "meeting" in q_lower or "discussion" in q_lower:
        subquestions.append({
            "subquestion": "What launch risks, compliance bottlenecks, or meeting decisions were recorded?",
            "source": "both"
        })
        
    if not subquestions:
        subquestions = [
            {"subquestion": f"Search Notion documentation relevant to: {question}", "source": "notion"},
            {"subquestion": f"Search Jira issue tracker for tickets relevant to: {question}", "source": "jira"}
        ]
        
    return subquestions

def synthesize_answer_llm(
    question: str, 
    evidence_items: List[Dict[str, Any]], 
    memory_facts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Synthesizes final answer with inline citation tags like [Jira #JIRA-101] or [Notion #NOTION-3],
    and extracts new key facts to remember.
    """
    client = get_anthropic_client()
    
    evidence_str = ""
    for idx, item in enumerate(evidence_items, 1):
        src_tag = f"[{'Jira #' + item['source_id'] if item['source'] == 'jira' else 'Notion #' + item['source_id']}]"
        evidence_str += f"\nItem {idx} {src_tag}:\nTitle/Summary: {item['title']}\nSource: {item['source']}\nID: {item['source_id']}\nSnippet: {item['snippet']}\nURL: {item['url']}\n"

    memory_str = "\n".join([f"- {f.get('fact_text', '')}" for f in memory_facts]) if memory_facts else "No prior memory context."

    if client:
        try:
            prompt = f"""You are an expert Project Management AI Assistant for Project X.
Answer the user's question thoroughly and accurately based ONLY on the provided Evidence and Memory Context.

User Question: "{question}"

Memory Context from Previous Turns:
{memory_str}

Retrieved Evidence Items:
{evidence_str}

REQUIREMENTS:
1. Write a comprehensive, well-formatted answer in Markdown.
2. Every factual claim MUST include inline citations referring to the evidence using exact tags like [Jira #JIRA-101] or [Notion #NOTION-3].
3. Make use of session memory if relevant to answer follow-up questions seamlessly.
4. Extract 2-4 concise, bullet-point new facts learned during this turn to save into memory.

Return strictly a JSON object with this shape:
{{
  "answer": "Markdown string containing answer with inline citation tags like [Jira #JIRA-101] or [Notion #NOTION-3]",
  "extracted_facts": ["Fact 1", "Fact 2"]
}}
"""
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}]
            )
            content = response.content[0].text
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            parsed = json.loads(content)
            return parsed
        except Exception as e:
            logger.error(f"Error in LLM synthesize: {e}")

    # Deterministic Synthesis Fallback (when API key isn't present or network fails)
    # Generates structured cited response directly from evidence items & memory
    ans_lines = [f"### Summary for: *{question}*\n"]
    extracted_facts = []

    if memory_facts:
        ans_lines.append("**Context from previous conversation:**")
        for mf in memory_facts[:3]:
            ans_lines.append(f"- {mf.get('fact_text')}")
        ans_lines.append("")

    ans_lines.append("Based on retrieved operational data from **Jira** and **Notion**:\n")
    
    jira_items = [e for e in evidence_items if e["source"] == "jira"]
    notion_items = [e for e in evidence_items if e["source"] == "notion"]

    if notion_items:
        ans_lines.append("#### Documentation & Architecture Updates (Notion)")
        for n in notion_items[:3]:
            tag = f"[Notion #{n['source_id']}]"
            ans_lines.append(f"- **{n['title']}** {tag}: {n['snippet']}")
            extracted_facts.append(f"{n['title']} documented in Notion ({n['source_id']}).")

    if jira_items:
        ans_lines.append("\n#### Active Tasks & Issues (Jira)")
        for j in jira_items[:4]:
            tag = f"[Jira #{j['source_id']}]"
            status_badge = f"`[{j.get('extra', {}).get('status', 'Open')}]`"
            assignee = j.get('extra', {}).get('assignee', 'Unassigned')
            ans_lines.append(f"- **{j['title']}** {status_badge} (Assignee: **{assignee}**) {tag}: {j['snippet']}")
            if j.get('extra', {}).get('status') == 'Blocked':
                extracted_facts.append(f"{j['source_id']} ({j['title']}) is BLOCKED and assigned to {assignee}.")
            else:
                extracted_facts.append(f"{j['source_id']} status is {j.get('extra', {}).get('status')} assigned to {assignee}.")

    if not evidence_items:
        ans_lines.append("No direct evidence items matched the query criteria.")

    final_answer = "\n".join(ans_lines)
    return {
        "answer": final_answer,
        "extracted_facts": extracted_facts[:4]
    }
