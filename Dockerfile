# Multi-stage production Dockerfile for Agentic RAG SaaS
# Targets:
#   - backend : FastAPI + LangGraph + Alembic + pgvector + Redis rate limiter
#   - gateway : Single-origin Nginx reverse proxy (`/` landing, `/app` React SPA, `/api/*` FastAPI)

# ============================================================================
# Stage 1: Build React SPA under `/app/` base path
# ============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
ARG VITE_GOOGLE_CLIENT_ID=""
ENV VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}
RUN npx tsc -b && npx vite build --base=/app/

# ============================================================================
# Stage 2: Production FastAPI + Alembic Backend
# ============================================================================
FROM python:3.11-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
COPY backend/evals ./evals
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

RUN python -m pip install --upgrade pip \
    && pip install . \
    && python -m app.db_setup \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/uploads /app/data \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]

# ============================================================================
# Stage 3: Single-Origin Nginx Reverse Proxy (`/` + `/app` + `/api/*`)
# ============================================================================
FROM nginx:1.27-alpine AS gateway

RUN rm -f /etc/nginx/conf.d/default.conf

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY landing/ /usr/share/nginx/html/
COPY --from=frontend-builder /build/frontend/dist/ /usr/share/nginx/html/app/

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/api/health || exit 1

# ============================================================================
# Stage 4 (Default): All-in-one Single-Origin Container for Railway / Render
# Serves `/` (landing), `/app` (React SPA), and `/api/*` (FastAPI SSE) on $PORT
# ============================================================================
FROM backend AS all-in-one

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx gettext-base \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/www/html/app /etc/nginx/templates

COPY landing/ /var/www/html/
COPY --from=frontend-builder /build/frontend/dist/ /var/www/html/app/
COPY deploy/nginx.railway.conf.template /etc/nginx/templates/default.conf.template
COPY deploy/start-all-in-one.sh /usr/local/bin/start-all-in-one.sh
RUN chmod +x /usr/local/bin/start-all-in-one.sh

ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -fsS http://127.0.0.1:${PORT}/api/health || exit 1

CMD ["/usr/local/bin/start-all-in-one.sh"]
