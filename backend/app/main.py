from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
import inspect
import logging
import os
from pathlib import Path as FilePath
import sqlite3
from typing import Any
import uuid

from fastapi import Depends, FastAPI, HTTPException, Path, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from langchain_core.messages import AIMessage, HumanMessage

from app.agent import (
    AgentError,
    AgentNotConfiguredError,
    AgentRecursionLimitError,
    BasicAgent,
    _message_content_to_text,
    configure_default_checkpointer,
    get_agent,
)
from app.db_setup import DEFAULT_DB_PATH
from app.persistence import (
    PersistenceError,
    PostgresPersistenceManager,
    init_optional_checkpointer_from_env,
)
from app.schemas import QueryRequest, QueryResponse, ThreadHistoryResponse, ThreadMessage
from app.streaming import sse_answer, sse_done, sse_error, sse_step, sse_trace

logger = logging.getLogger(__name__)

THREAD_ID_PATTERN = r"^[a-zA-Z0-9_\-]{1,64}$"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    manager: PostgresPersistenceManager | None = None
    try:
        manager, checkpointer = init_optional_checkpointer_from_env()
        configure_default_checkpointer(checkpointer)
        app.state.persistence_manager = manager
        app.state.checkpointer = checkpointer
    except PersistenceError as exc:
        logger.warning("PostgreSQL checkpointer unavailable on startup: %s", exc)
        configure_default_checkpointer(None)
        app.state.persistence_manager = None
        app.state.checkpointer = None

    try:
        yield
    finally:
        configure_default_checkpointer(None)
        if manager is not None:
            manager.close()


app = FastAPI(lifespan=lifespan)

cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5500")
cors_origins = [orig.strip() for orig in cors_origins_env.split(",") if orig.strip()]
if not cors_origins:
    cors_origins = ["http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["POST", "GET", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Sprint 1 — Auth + Multi-tenant routes (Alok owns these)
# ---------------------------------------------------------------------------
from app.middleware.csrf import CSRFOriginMiddleware  # noqa: E402
from app.routes.auth import router as auth_router  # noqa: E402
from app.routes.conversations import router as conv_router  # noqa: E402

app.add_middleware(CSRFOriginMiddleware)
app.include_router(auth_router, prefix="/api")
app.include_router(conv_router, prefix="/api")


def _accepts_thread_id(fn: object) -> bool:
    try:
        sig = inspect.signature(fn)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return "thread_id" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/deep")
def deep_health_check() -> dict[str, Any]:
    components: dict[str, str] = {}
    is_healthy = True

    # 1. Database accessibility check
    env_db = os.getenv("SQLITE_DB_PATH")
    db_path = FilePath(env_db).resolve() if env_db else DEFAULT_DB_PATH.resolve()
    if not db_path.exists():
        components["database"] = f"down: database file not found at {db_path}"
        is_healthy = False
    else:
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM products")
                count = cursor.fetchone()[0]
                components["database"] = f"ok ({count} products)"
        except Exception as exc:
            components["database"] = f"down: {type(exc).__name__}"
            is_healthy = False

    # 2. LLM Provider configuration check
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    components["llm_provider"] = "configured" if api_key else "not_configured"

    # 3. Checkpointer check
    pg_url = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    components["checkpointer"] = "postgres" if pg_url else "memory_or_disabled"

    status_str = "ok" if is_healthy else "degraded"
    if not is_healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": status_str, "components": components},
        )
    return {"status": status_str, "components": components}


@app.post("/query", response_model=QueryResponse, response_model_exclude_none=True)
def query_agent(
    request: QueryRequest,
    agent: BasicAgent = Depends(get_agent),
) -> QueryResponse:
    has_checkpointer = getattr(agent, "checkpointer", None) is not None
    active_thread_id: str | None = (
        request.thread_id
        if request.thread_id is not None
        else (str(uuid.uuid4()) if has_checkpointer else None)
    )

    try:
        if active_thread_id is not None and _accepts_thread_id(agent.query_with_evidence):
            answer, evidence = agent.query_with_evidence(
                request.query,
                thread_id=active_thread_id,
            )
            resolved_thread_id = active_thread_id
        else:
            answer, evidence = agent.query_with_evidence(request.query)
            resolved_thread_id = active_thread_id
        return QueryResponse(
            answer=answer,
            evidence=evidence,
            thread_id=resolved_thread_id,
        )
    except AgentNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except AgentRecursionLimitError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except AgentError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@app.post("/query/stream")
def stream_agent(
    request: QueryRequest,
    agent: BasicAgent = Depends(get_agent),
) -> StreamingResponse:
    has_checkpointer = getattr(agent, "checkpointer", None) is not None
    active_thread_id: str | None = (
        request.thread_id
        if request.thread_id is not None
        else (str(uuid.uuid4()) if has_checkpointer else None)
    )

    def generate() -> Iterator[str]:
        done_emitted = False
        try:
            # Emit planner start immediately
            yield sse_step("planner", "start")

            stream_kwargs: dict[str, Any] = {}
            if active_thread_id is not None and _accepts_thread_id(agent.stream_with_evidence):
                stream_kwargs["thread_id"] = active_thread_id

            for event_dict in agent.stream_with_evidence(request.query, **stream_kwargs):
                event = event_dict.get("event")
                data = event_dict.get("data", {})

                if event == "step":
                    node = data.get("node")
                    status_val = data.get("status")
                    if node and status_val:
                        yield sse_step(node, status_val)
                        # If planner just ended, emit worker start
                        if node == "planner" and status_val == "end":
                            yield sse_step("worker", "start")

                elif event == "answer":
                    # Optionally emit LangSmith trace URL
                    run_id = data.get("run_id") or getattr(agent, "last_run_id", None)
                    trace_frame = sse_trace(run_id)
                    if trace_frame:
                        yield trace_frame
                    raw_answer = data.get("answer")
                    answer_text = raw_answer if isinstance(raw_answer, str) else ""
                    yield sse_answer(
                        answer_text,
                        data.get("evidence"),
                        data.get("thread_id") or active_thread_id,
                    )

                elif event == "error":
                    yield sse_error(data.get("message", "Unknown error"))

                elif event == "done":
                    done_emitted = True
                    yield sse_done()

            if not done_emitted:
                done_emitted = True
                yield sse_done()

        except Exception as exc:
            logger.exception("Streaming execution failed: %s", exc)
            yield sse_error(str(exc) or f"Execution error ({type(exc).__name__})")
            if not done_emitted:
                done_emitted = True
                yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get(
    "/threads/{thread_id}",
    response_model=ThreadHistoryResponse,
    response_model_exclude_none=True,
)
def get_thread_history(
    thread_id: str = Path(
        ...,
        pattern=THREAD_ID_PATTERN,
        description="Unique conversation thread ID (1-64 alphanumeric/underscore/hyphen)",
    ),
    agent: BasicAgent = Depends(get_agent),
) -> ThreadHistoryResponse:
    state = agent.get_thread_state(thread_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation thread not found.",
        )

    messages: list[ThreadMessage] = []
    for msg in state.get("messages") or []:
        if isinstance(msg, HumanMessage):
            messages.append(
                ThreadMessage(role="user", content=_message_content_to_text(msg.content))
            )
        elif isinstance(msg, AIMessage):
            messages.append(
                ThreadMessage(role="assistant", content=_message_content_to_text(msg.content))
            )

    raw_evidence = state.get("evidence")
    evidence = raw_evidence if isinstance(raw_evidence, list) else None
    return ThreadHistoryResponse(
        thread_id=thread_id.strip(),
        messages=messages,
        evidence=evidence,
    )
