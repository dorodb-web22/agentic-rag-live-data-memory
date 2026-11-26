"""Sprint 3 — Structural verification for Alembic 002, Docker, Nginx & CI merge gate."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from app.db.models import Base, DocumentChunk

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_document_chunk_model_and_alembic_002_revision() -> None:
    assert "document_chunks" in Base.metadata.tables
    table = Base.metadata.tables["document_chunks"]
    expected_cols = {
        "id",
        "user_id",
        "provider",
        "external_id",
        "chunk_index",
        "citation_key",
        "title",
        "url",
        "chunk_text",
        "metadata_json",
        "embedding",
        "tsv",
    }
    assert expected_cols.issubset(set(table.columns.keys()))
    assert DocumentChunk.__tablename__ == "document_chunks"

    mig_path = REPO_ROOT / "backend" / "alembic" / "versions" / "002_enable_pgvector_and_document_chunks.py"
    assert mig_path.exists()
    spec = importlib.util.spec_from_file_location("mig_002", mig_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "002"
    assert mod.down_revision == "001"


def test_single_origin_deploy_and_ci_gate_configs_present() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:20-alpine AS frontend-builder" in dockerfile
    assert "vite build --base=/app/" in dockerfile
    assert "FROM python:3.11-slim AS backend" in dockerfile
    assert "FROM nginx:1.27-alpine AS gateway" in dockerfile
    assert "alembic upgrade head" in dockerfile

    nginx_conf = (REPO_ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    assert "location /api/" in nginx_conf
    assert 'X-Accel-Buffering "no"' in nginx_conf
    assert "proxy_buffering off;" in nginx_conf
    assert "location = /app" in nginx_conf
    assert "location /app/" in nginx_conf

    compose_prod = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "pgvector/pgvector:pg16" in compose_prod
    assert "redis:7-alpine" in compose_prod
    assert "gateway:" in compose_prod

    ci_yml = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "deepeval-gate:" in ci_yml
    assert "evals.run_eval" in ci_yml
