# Backend

FastAPI service exposing `GET /health` and `POST /query` (`{"query": "..."}` → `{"answer": "...", "evidence": [...]}`).

## Features

- **Agentic RAG with LangGraph**: StateGraph workflow managing retrieval and generation.
- **MCP SQLite Data Retrieval**: Official Model Context Protocol (`mcp-server-sqlite`) client communicating over stdio to query a local SQLite database with read-only security constraints.
- **Evidence-Grounded Answers**: Responses formatted in Markdown with structured supporting database evidence tables.
- **Provider Support**: Groq (`openai/gpt-oss-20b`) and OpenAI (`gpt-4o-mini`).

## Setup

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then edit .env and add your key; never commit it
```

### Initialize Demonstration Database

To initialize or reset the local SQLite demonstration database:

```bash
.venv/bin/python3 -m app.db_setup
```

This creates `backend/data/demo.db` and populates the `products` table with seed records (Starter, Professional, Enterprise packages, etc.).

## Configuration (environment variables)

| Variable | Purpose | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai` or `groq` | `openai` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Used when provider is `openai` | — / `gpt-4o-mini` |
| `GROQ_API_KEY` | Required when provider is `groq` | — |
| `GROQ_MODEL` | Groq model name | `openai/gpt-oss-20b` |
| `GROQ_BASE_URL` | Groq OpenAI-compatible endpoint | `https://api.groq.com/openai/v1` |
| `SQLITE_DB_PATH` | Path to demonstration SQLite database | `data/demo.db` |

Example `.env` for Groq:

```
LLM_PROVIDER=groq
GROQ_API_KEY=<your key>
GROQ_MODEL=openai/gpt-oss-20b
SQLITE_DB_PATH=data/demo.db
```

## Running the Application

### 1. Start the Backend (Port 8000)

```bash
cd backend
set -a; source .env; set +a
.venv/bin/uvicorn app.main:app --port 8000 --reload
```

### 2. Start the Frontend (Port 5173)

In a separate terminal:

```bash
cd frontend
npm run dev
```

Open your browser at http://localhost:5173.

## Running Tests

```bash
cd backend
.venv/bin/pytest -v
```

All 34 tests should pass:
- 7 tests in `test_agent.py`
- 8 tests in `test_hash_map.py`
- 5 tests in `test_main.py`
- 14 tests in `test_mcp_retrieval.py`

## Viva Demonstration Scenarios

1. **Evidence-Grounded Database Query**:
   - Query: `What is the price of the Enterprise package, and what database information supports your answer?`
   - Result: Agent invokes MCP tool `read_query` on SQLite `products` table, retrieves record ID 3 ($5,000.00), and outputs the price with a Markdown table under `### Supporting Evidence`.

2. **Negative Test / Unknown Product (No Hallucination)**:
   - Query: `What is the price of the Quantum package?`
   - Result: Agent queries SQLite via MCP tool, receives 0 rows, and explicitly informs the user that no matching record exists rather than fabricating a price.

3. **General Knowledge (Retrieval Bypass)**:
   - Query: `What is retrieval augmented generation?`
   - Result: Agent detects that no database query is required, bypasses MCP retrieval, and answers directly from LLM knowledge.

## Error responses

- `503` — provider not configured (missing key or unsupported `LLM_PROVIDER`)
- `502` — provider or MCP failure (e.g. invalid query, database missing, LLM error)
- `422` — missing or blank `query`
