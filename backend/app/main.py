from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import inspect
import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.agent import (
    AgentError,
    AgentNotConfiguredError,
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
    except AgentError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
