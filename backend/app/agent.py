import logging
import os
from functools import lru_cache
from typing import Protocol, TypedDict

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)


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
        # Groq exposes an OpenAI-compatible API, so ChatOpenAI works with a custom base_url.
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


def create_agent_graph(llm: SupportsInvoke | None = None) -> SupportsInvoke:
    model = llm or create_llm()

    def call_llm(state: AgentState) -> AgentState:
        response = model.invoke([HumanMessage(content=state["query"])])
        answer = _message_content_to_text(getattr(response, "content", response))
        return {"query": state["query"], "answer": answer}

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_llm)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    return graph.compile()


class BasicAgent:
    def __init__(self, graph: SupportsInvoke | None = None) -> None:
        self._graph = graph

    def answer(self, query: str) -> str:
        if self._graph is None:
            self._graph = create_agent_graph()
        try:
            result = self._graph.invoke({"query": query})
        except AgentError:
            raise
        except Exception as error:
            # Provider failures (bad key, rate limit, unknown model) become a 502
            # instead of an unhandled 500. Only the exception type is exposed.
            logger.exception("LLM request failed")
            raise AgentError(f"LLM request failed ({type(error).__name__}).") from error
        if not isinstance(result, dict) or not isinstance(result.get("answer"), str):
            raise AgentError("Agent returned an invalid response.")
        return result["answer"]


@lru_cache
def get_agent() -> BasicAgent:
    return BasicAgent()
