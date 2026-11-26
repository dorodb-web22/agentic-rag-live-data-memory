from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import inspect
import logging
import os
from pathlib import Path as FilePath
import sqlite3
import time
from typing import Any
import uuid

from fastapi import Depends, FastAPI, HTTPException, Path, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import (
    AgentError,
    AgentNotConfiguredError,
    AgentRecursionLimitError,
    BasicAgent,
    _message_content_to_text,
    configure_default_checkpointer,
    get_agent,
)
from app.auth.google import current_user
from app.db.conversations import record_conversation_turn
from app.db.session import get_db
from app.db_setup import DEFAULT_DB_PATH
from app.persistence import (
    PersistenceError,
    PostgresPersistenceManager,
    init_optional_checkpointer_from_env,
    resolve_database_url,
)
from app.schemas import QueryRequest, QueryResponse, ThreadHistoryResponse, ThreadMessage
import app.streaming as streaming_mod
from app.streaming import (
    aresolve_trace_url,
    sse_answer,
    sse_done,
    sse_error,
    sse_keepalive,
    sse_step,
    sse_trace,
    sse_trace_from_url,
)

logger = logging.getLogger(__name__)

THREAD_ID_PATTERN = r"^[a-zA-Z0-9_\-]{1,64}$"


async def _init_optional_async_checkpointer() -> tuple[AsyncConnectionPool[Any] | None, AsyncPostgresSaver | None]:
    """Open an AsyncConnectionPool and initialize AsyncPostgresSaver when DATABASE_URL is reachable."""
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if not raw_url:
        return None, None

    conninfo = resolve_database_url(raw_url)
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "connect_timeout": 5,
        },
    )
    await pool.open(wait=True, timeout=7.0)
    try:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        return pool, saver
    except Exception:
        await pool.close()
        raise


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    manager: PostgresPersistenceManager | None = None
    sync_saver = None
    async_pool: AsyncConnectionPool[Any] | None = None
    async_saver: AsyncPostgresSaver | None = None

    try:
        manager, sync_saver = await asyncio.to_thread(init_optional_checkpointer_from_env)
    except PersistenceError as exc:
        logger.warning("Sync PostgreSQL checkpointer unavailable on startup: %s", exc)
        manager, sync_saver = None, None

    try:
        async_pool, async_saver = await _init_optional_async_checkpointer()
    except Exception as exc:
        logger.warning("Async PostgreSQL checkpointer unavailable on startup: %s", exc)
        async_pool, async_saver = None, None

    configure_default_checkpointer(sync_saver, async_checkpointer=async_saver)
    app.state.persistence_manager = manager
    app.state.checkpointer = sync_saver
    app.state.async_pool = async_pool
    app.state.async_checkpointer = async_saver

    try:
        yield
    finally:
        configure_default_checkpointer(None, async_checkpointer=None)
        if async_pool is not None:
            try:
                await async_pool.close()
            except Exception:
                logger.exception("Error closing async PostgreSQL pool")
        if manager is not None:
            await asyncio.to_thread(manager.close)


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
# Auth, Multi-tenant Conversations & Integrations routes (Alok owns routers)
# ---------------------------------------------------------------------------
from app.middleware.csrf import CSRFOriginMiddleware  # noqa: E402
from app.middleware.rate_limit import RateLimitMiddleware  # noqa: E402
from app.routes.auth import router as auth_router  # noqa: E402
from app.routes.conversations import router as conv_router  # noqa: E402

app.add_middleware(RateLimitMiddleware)
app.add_middleware(CSRFOriginMiddleware)
app.include_router(auth_router, prefix="/api")
app.include_router(conv_router, prefix="/api")

# ---------------------------------------------------------------------------
# Sprint 2 — Per-user OAuth Connector Registry (Alok owns these)
# ---------------------------------------------------------------------------
from app.routes.integrations import router as integrations_router  # noqa: E402

app.include_router(integrations_router, prefix="/api")


def _accepts_thread_id(fn: object) -> bool:
    try:
        sig = inspect.signature(fn)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return "thread_id" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )


def _check_sqlite_health() -> tuple[bool, str]:
    env_db = os.getenv("SQLITE_DB_PATH")
    db_path = FilePath(env_db).resolve() if env_db else DEFAULT_DB_PATH.resolve()
    if not db_path.exists():
        return False, f"down: database file not found at {db_path}"
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            count = cursor.fetchone()[0]
            return True, f"ok ({count} products)"
    except Exception as exc:
        return False, f"down: {type(exc).__name__}"


@app.get("/health")
@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/deep")
@app.get("/api/health/deep")
async def deep_health_check() -> dict[str, Any]:
    components: dict[str, str] = {}
    db_ok, db_msg = await asyncio.to_thread(_check_sqlite_health)
    components["database"] = db_msg
    is_healthy = db_ok

    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY") or "").strip()
    components["llm_provider"] = "configured" if api_key else "not_configured"

    pg_url = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    components["checkpointer"] = "postgres" if pg_url else "memory_or_disabled"

    status_str = "ok" if is_healthy else "degraded"
    if not is_healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": status_str, "components": components},
        )
    return {"status": status_str, "components": components}


# ---------------------------------------------------------------------------
# Authenticated Multi-Tenant Async Endpoints (/api/query & /api/query/stream)
# ---------------------------------------------------------------------------


@app.post("/api/query", response_model=QueryResponse, response_model_exclude_none=True)
async def api_query_agent(
    payload: QueryRequest,
    user: dict[str, Any] = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    agent: BasicAgent = Depends(get_agent),
) -> QueryResponse:
    user_id = str(user["user_id"])
    resolved_thread_id = payload.thread_id or str(uuid.uuid4())

    try:
        if hasattr(agent, "aquery_with_evidence"):
            answer, evidence = await agent.aquery_with_evidence(
                payload.query,
                thread_id=resolved_thread_id,
                user_id=user_id,
                db=db,
            )
        else:
            answer, evidence = await asyncio.to_thread(
                agent.query_with_evidence,
                payload.query,
                resolved_thread_id,
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

    trace_url = await aresolve_trace_url(getattr(agent, "last_run_id", None))
    await record_conversation_turn(
        db,
        user_id=user_id,
        thread_id=resolved_thread_id,
        user_msg=payload.query,
        assistant_msg=answer,
        evidence=evidence,
        trace_url=trace_url,
    )

    return QueryResponse(
        answer=answer,
        evidence=evidence,
        thread_id=resolved_thread_id,
    )


@app.post("/api/query/stream")
async def api_stream_agent(
    payload: QueryRequest,
    raw_request: Request,
    user: dict[str, Any] = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    agent: BasicAgent = Depends(get_agent),
) -> StreamingResponse:
    user_id = str(user["user_id"])
    resolved_thread_id = payload.thread_id or str(uuid.uuid4())

    async def generate() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        done_emitted = False

        async def _produce() -> None:
            try:
                async for item in agent.astream_with_evidence(
                    payload.query,
                    thread_id=resolved_thread_id,
                    user_id=user_id,
                    db=db,
                ):
                    await queue.put(item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Async producer failed: %s", exc)
                await queue.put(
                    {
                        "event": "error",
                        "data": {"message": str(exc) or f"Execution error ({type(exc).__name__})"},
                    }
                )
                await queue.put({"event": "done", "data": {}})
            finally:
                await queue.put(None)

        producer_task = asyncio.create_task(_produce())
        keepalive_interval = float(getattr(streaming_mod, "KEEPALIVE_INTERVAL_SECONDS", 15.0))
        poll_slice = min(keepalive_interval, 0.2)
        last_activity = time.monotonic()

        try:
            while True:
                if await raw_request.is_disconnected():
                    producer_task.cancel()
                    try:
                        await producer_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    return

                try:
                    event_dict = await asyncio.wait_for(queue.get(), timeout=poll_slice)
                except asyncio.TimeoutError:
                    now_mono = time.monotonic()
                    if now_mono - last_activity >= keepalive_interval:
                        last_activity = now_mono
                        yield sse_keepalive()
                    continue

                if event_dict is None:
                    break

                last_activity = time.monotonic()
                event = event_dict.get("event")
                data = event_dict.get("data", {})

                if event == "step":
                    node = data.get("node")
                    status_val = data.get("status")
                    if node and status_val:
                        yield sse_step(node, status_val)

                elif event == "answer":
                    run_id = data.get("run_id") or getattr(agent, "last_run_id", None)
                    trace_url = await aresolve_trace_url(run_id)
                    raw_answer = data.get("answer")
                    answer_text = raw_answer if isinstance(raw_answer, str) else ""
                    evidence = data.get("evidence")
                    turn_tid = data.get("thread_id") or resolved_thread_id

                    if not await raw_request.is_disconnected():
                        try:
                            await record_conversation_turn(
                                db,
                                user_id=user_id,
                                thread_id=turn_tid,
                                user_msg=payload.query,
                                assistant_msg=answer_text,
                                evidence=evidence,
                                trace_url=trace_url,
                            )
                            await db.commit()
                        except Exception as persist_exc:
                            logger.exception("Failed to persist conversation turn: %s", persist_exc)

                    trace_frame = sse_trace_from_url(trace_url)
                    if trace_frame:
                        yield trace_frame
                    yield sse_answer(answer_text, evidence, turn_tid)

                elif event == "error":
                    yield sse_error(data.get("message", "Unknown error"))

                elif event == "done":
                    done_emitted = True
                    yield sse_done()

            if not done_emitted and not await raw_request.is_disconnected():
                done_emitted = True
                yield sse_done()

        except asyncio.CancelledError:
            producer_task.cancel()
            raise
        except Exception as exc:
            logger.exception("Streaming endpoint failed: %s", exc)
            yield sse_error(str(exc) or f"Execution error ({type(exc).__name__})")
            if not done_emitted:
                done_emitted = True
                yield sse_done()
        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except (asyncio.CancelledError, Exception):
                    pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Legacy Endpoints (/query, /query/stream, /threads/{thread_id})
# Retained for backward compatibility with Week 5-7 test suites
# ---------------------------------------------------------------------------


@app.post("/query", response_model=QueryResponse, response_model_exclude_none=True)
async def query_agent(
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
            answer, evidence = await asyncio.to_thread(
                agent.query_with_evidence,
                request.query,
                thread_id=active_thread_id,
            )
            resolved_thread_id = active_thread_id
        else:
            answer, evidence = await asyncio.to_thread(agent.query_with_evidence, request.query)
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
async def stream_agent(
    request: QueryRequest,
    agent: BasicAgent = Depends(get_agent),
) -> StreamingResponse:
    has_checkpointer = getattr(agent, "checkpointer", None) is not None
    active_thread_id: str | None = (
        request.thread_id
        if request.thread_id is not None
        else (str(uuid.uuid4()) if has_checkpointer else None)
    )

    def generate() -> Any:
        done_emitted = False
        try:
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
                        if node == "planner" and status_val == "end":
                            yield sse_step("worker", "start")

                elif event == "answer":
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
async def get_thread_history(
    thread_id: str = Path(
        ...,
        pattern=THREAD_ID_PATTERN,
        description="Unique conversation thread ID (1-64 alphanumeric/underscore/hyphen)",
    ),
    agent: BasicAgent = Depends(get_agent),
) -> ThreadHistoryResponse:
    state = await asyncio.to_thread(agent.get_thread_state, thread_id)
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
