# Backend

FastAPI service exposing `GET /health` and `POST /query` (`{"query": "..."}` → `{"answer": "..."}`).

## Setup

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # then edit .env and add your key; never commit it
```

## Configuration (environment variables)

| Variable | Purpose | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai` or `groq` | `openai` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Used when provider is `openai` | — / `gpt-4o-mini` |
| `GROQ_API_KEY` | Required when provider is `groq` | — |
| `GROQ_MODEL` | Groq model name | `openai/gpt-oss-20b` |
| `GROQ_BASE_URL` | Groq OpenAI-compatible endpoint | `https://api.groq.com/openai/v1` |

Example `.env` for Groq:

```
LLM_PROVIDER=groq
GROQ_API_KEY=<your key>
GROQ_MODEL=openai/gpt-oss-20b
```

## Run

The app does not load `.env` itself, so export it into the shell first:

```bash
set -a; source .env; set +a
.venv/bin/uvicorn app.main:app --port 8000
```

## Test

```bash
.venv/bin/pytest
```

## Error responses

- `503` — provider not configured (missing key or unsupported `LLM_PROVIDER`)
- `502` — the LLM provider call failed (e.g. rejected key, rate limit, unknown model)
- `422` — missing or blank `query`
