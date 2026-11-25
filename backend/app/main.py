from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
import inspect
import logging
from typing import Any
import uuid

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agent import (
    AgentError,
    AgentNotConfiguredError,
    AgentRecursionLimitError,
    BasicAgent,
    configure_default_checkpointer,
    get_agent,
)
from app.persistence import (
    PersistenceError,
    PostgresPersistenceManager,
    init_optional_checkpointer_from_env,
)
from app.schemas import QueryRequest, QueryResponse
from app.streaming import sse_answer, sse_done, sse_error, sse_step, sse_trace

logger = logging.getLogger(__name__)


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


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
            resolved_thread_id = getattr(agent, "last_thread_id", None) or active_thread_id
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
                    run_id = getattr(agent, "last_run_id", None)
                    trace_frame = sse_trace(run_id)
                    if trace_frame:
                        yield trace_frame
                    raw_answer = data.get("answer")
                    answer_text = raw_answer if isinstance(raw_answer, str) else ""
                    yield sse_answer(
                        answer_text,
                        data.get("evidence"),
                        data.get("thread_id"),
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
            yield sse_error(str(exc))
            if not done_emitted:
                done_emitted = True
                yield sse_done()

    return StreamingResponse(generate(), media_type="text/event-stream")
