from pydantic import BaseModel, Field, field_validator

MAX_QUERY_LENGTH = 2000


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
        return cleaned or None


class QueryResponse(BaseModel):
    answer: str
    evidence: list[dict[str, object]] | None = None
    thread_id: str | None = None
