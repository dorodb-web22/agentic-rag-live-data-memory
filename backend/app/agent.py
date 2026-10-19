import json
import logging
import os
import re
from functools import lru_cache
from typing import Any, Protocol, TypedDict

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.mcp_client import McpClientError, SqliteMcpClient

logger = logging.getLogger(__name__)

DATABASE_KEYWORDS = {
    "product", "products", "price", "prices", "cost", "costs", "package", "packages",
    "starter", "professional", "enterprise", "subscription", "subscriptions",
    "catalog", "inventory", "database", "table", "sqlite", "tier", "tiers",
    "plan", "plans", "pricing", "how much", "add-on", "addon", "service", "services",
    "storage", "support",
}

STOP_WORDS = {
    "the", "a", "an", "this", "that", "each", "any", "every", "what", "which",
    "available", "our", "all", "new", "these", "those", "some", "my", "your",
}


def is_database_query(query: str) -> bool:
    """Determine whether a natural language query targets SQLite database information."""
    lowered = query.lower()
    return any(keyword in lowered for keyword in DATABASE_KEYWORDS)


def build_sql_query(user_query: str) -> tuple[str, str | None]:
    """Construct a safe read-only SELECT statement tailored to the user query."""
    lowered = user_query.lower()
    known_products = ["enterprise", "starter", "professional", "storage", "support"]
    for prod in known_products:
        if prod in lowered:
            return (
                f"SELECT id, name, description, price, category FROM products WHERE LOWER(name) LIKE '%{prod}%'",
                prod,
            )

    match = re.search(r"([a-zA-Z0-9_\-]+)\s+(?:package|plan|tier|product)", lowered)
    if match and match.group(1) not in STOP_WORDS:
        term = match.group(1)
        return (
            f"SELECT id, name, description, price, category FROM products WHERE LOWER(name) LIKE '%{term}%'",
            term,
        )

    return "SELECT id, name, description, price, category FROM products", None


class AgentError(RuntimeError):
    """Raised when the agent cannot produce an answer."""


class AgentNotConfiguredError(AgentError):
    """Raised when the configured LLM provider is missing required settings."""


class SupportsInvoke(Protocol):
    def invoke(self, input: object) -> object:
        pass


class AgentState(TypedDict):
    query: str
    answer: str


def _message_content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return str(content)


def create_llm() -> SupportsInvoke:
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise AgentNotConfiguredError("GROQ_API_KEY is required to call the LLM.")
        return ChatOpenAI(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            api_key=api_key,
            base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        )

    if provider != "openai":
        raise AgentNotConfiguredError(
            f"Unsupported LLM_PROVIDER '{provider}'. Use 'openai' or 'groq'."
        )

    if not os.getenv("OPENAI_API_KEY"):
        raise AgentNotConfiguredError("OPENAI_API_KEY is required to call the LLM.")

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return ChatOpenAI(model=model)


def create_agent_graph(
    llm: SupportsInvoke | None = None,
    mcp_client: SqliteMcpClient | None = None,
) -> SupportsInvoke:
    model = llm or create_llm()
    client = mcp_client or SqliteMcpClient()

    def call_llm(state: AgentState) -> AgentState:
        query = state["query"]
        if is_database_query(query):
            sql_query, _ = build_sql_query(query)
            try:
                records = client.execute_query_sync(sql_query)
            except McpClientError as exc:
                logger.exception("MCP retrieval failed: %s", exc)
                raise AgentError(f"MCP retrieval failed: {str(exc)}") from exc
            except Exception as exc:
                logger.exception("Unexpected retrieval error: %s", exc)
                raise AgentError(f"Database retrieval error ({type(exc).__name__}).") from exc

            if records:
                evidence_text = json.dumps(records, indent=2)
                prompt = (
                    "You are an Agentic RAG Assistant. Answer the user question based on the retrieved SQLite database records.\n\n"
                    "Database Source: SQLite (via Model Context Protocol - MCP)\n"
                    "Table: products\n"
                    f"Retrieved Records:\n{evidence_text}\n\n"
                    "Instructions:\n"
                    "1. Provide a direct, factual answer to the user question in Markdown.\n"
                    "2. Under a '### Supporting Evidence' section, display the retrieved database facts (Table, Record ID, Name, Price, Category) in a Markdown table.\n"
                    "3. Be strictly grounded in the database records provided above.\n\n"
                    f"User Question: {query}"
                )
            else:
                prompt = (
                    "You are an Agentic RAG Assistant. Answer the user question based on the retrieved SQLite database records.\n\n"
                    "Database Source: SQLite (via Model Context Protocol - MCP)\n"
                    "Table: products\n"
                    "Retrieved Records: No matching records found.\n\n"
                    "Instructions:\n"
                    "1. Clearly inform the user that no matching record exists in the database for the requested item.\n"
                    "2. Under a '### Supporting Evidence' section, state that the database query returned 0 records.\n"
                    "3. Do NOT invent, assume, or fabricate any prices or product details.\n\n"
                    f"User Question: {query}"
                )
            response = model.invoke([HumanMessage(content=prompt)])
        else:
            response = model.invoke([HumanMessage(content=query)])

        answer = _message_content_to_text(getattr(response, "content", response))
        return {"query": query, "answer": answer}

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_llm)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    return graph.compile()


class BasicAgent:
    def __init__(
        self,
        graph: SupportsInvoke | None = None,
        mcp_client: SqliteMcpClient | None = None,
    ) -> None:
        self._graph = graph
        self._mcp_client = mcp_client

    def answer(self, query: str) -> str:
        answer, _ = self.query_with_evidence(query)
        return answer

    def query_with_evidence(self, query: str) -> tuple[str, list[dict[str, Any]] | None]:
        if self._graph is None:
            self._graph = create_agent_graph(mcp_client=self._mcp_client)
        try:
            result = self._graph.invoke({"query": query})
        except AgentError:
            raise
        except Exception as error:
            logger.exception("LLM request failed")
            raise AgentError(f"LLM request failed ({type(error).__name__}).") from error
        if not isinstance(result, dict) or not isinstance(result.get("answer"), str):
            raise AgentError("Agent returned an invalid response.")

        # If it was a database query, retrieve the matching records for evidence field
        evidence = None
        if is_database_query(query):
            client = self._mcp_client or SqliteMcpClient()
            sql, _ = build_sql_query(query)
            try:
                evidence = client.execute_query_sync(sql)
            except Exception:
                evidence = None

        return result["answer"], evidence


@lru_cache
def get_agent() -> BasicAgent:
    return BasicAgent()
