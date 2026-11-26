# Backend

FastAPI service exposing `GET /health` and `POST /query` (`{"query": "...", "thread_id": "..."}` → `{"answer": "...", "evidence": [...], "thread_id": "..."}`).

## Features

- **Agentic RAG with LangGraph**: `planner_node` → `worker_node` `StateGraph` workflow managing retrieval and grounded synthesis.
- **PostgreSQL Checkpointer Persistence (Week 5)**: Thread-scoped conversational memory powered by `langgraph-checkpoint-postgres` (`PostgresSaver`) and `psycopg_pool.ConnectionPool`.
- **Grounded Inline Citations (Week 5)**: Mandatory `[Product-{id}]` inline citations validated against retrieved SQLite MCP records.
- **MCP SQLite & GitHub Data Retrieval**: Official Model Context Protocol (`mcp-server-sqlite` and `@modelcontextprotocol/server-github`) clients over stdio with read-only security constraints and subprocess timeouts.
- **Provider Support**: Groq (`openai/gpt-oss-20b`) and OpenAI (`gpt-4o-mini`).

## Setup

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then edit .env and add your key; never commit it
```

### Start Local PostgreSQL (Week 5 Persistence)

From the repository root:

```bash
docker compose up -d
```

This starts PostgreSQL 16 on `localhost:5432` (`agentic_rag` database). On startup, FastAPI's `lifespan` automatically runs `PostgresSaver.setup()` to initialize LangGraph's checkpoint tables.

### Initialize Demonstration SQLite Database

To initialize or reset the local SQLite demonstration database:

```bash
.venv/bin/python3 -m app.db_setup
```

## Configuration (environment variables)

| Variable | Purpose | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai` or `groq` | `openai` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Used when provider is `openai` | — / `gpt-4o-mini` |
| `GROQ_API_KEY` | Required when provider is `groq` | — |
| `GROQ_MODEL` | Groq model name | `openai/gpt-oss-20b` |
| `GROQ_BASE_URL` | Groq OpenAI-compatible endpoint | `https://api.groq.com/openai/v1` |
| `SQLITE_DB_PATH` | Path to demonstration SQLite database | `data/demo.db` |
| `DATABASE_URL` | PostgreSQL URI for LangGraph `PostgresSaver` checkpoints | — (optional in unit tests) |
| `POSTGRES_POOL_MIN_SIZE` / `POSTGRES_POOL_MAX_SIZE` | Psycopg connection pool bounds | `1` / `10` |

## Running Tests

```bash
cd backend
.venv/bin/pytest -v
```
