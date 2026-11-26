import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_QUERY_LENGTH = 2000
THREAD_ID_PATTERN = r"^[a-zA-Z0-9_\-]{1,64}$"


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    thread_id: str | None = Field(default=None)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("Query must not be blank.")
        return query

    @field_validator("thread_id")
    @classmethod
    def normalize_thread_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not re.match(THREAD_ID_PATTERN, cleaned):
            raise ValueError("thread_id must be 1-64 alphanumeric characters, underscores, or hyphens.")
        return cleaned


class QueryResponse(BaseModel):
    answer: str
    evidence: list[dict[str, object]] | None = None
    thread_id: str | None = None


class ThreadMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ThreadHistoryResponse(BaseModel):
    thread_id: str
    messages: list[ThreadMessage]
    evidence: list[dict[str, object]] | None = None
