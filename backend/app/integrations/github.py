"""GitHub connector — read-only OAuth: issues, PRs, repositories.

OAuth scopes requested: repo (read-only public + private repos)
  Alternatively: public_repo for public-only access.

Each user connects their own GitHub account.
Required env vars:
  GITHUB_OAUTH_CLIENT_ID     — GitHub OAuth App client ID
  GITHUB_OAUTH_CLIENT_SECRET — GitHub OAuth App client secret
  APP_BASE_URL               — callback base
"""
from __future__ import annotations

import logging
import os
import re
import urllib.parse
from typing import Any

import httpx

from app.integrations.base import BaseConnector
from app.integrations.registry import register

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

_GITHUB_PROVIDERS = {"pull request", "pull requests", "pr", "prs"}


def _app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def build_github_auth_url(state: str) -> str:
    params = {
        "client_id": os.environ["GITHUB_OAUTH_CLIENT_ID"],
        "redirect_uri": f"{_app_base_url()}/api/integrations/github/callback",
        "scope": "repo",  # read-only repos, issues, PRs
        "state": state,
    }
    return GITHUB_AUTH_URL + "?" + urllib.parse.urlencode(params)


async def exchange_github_code(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": os.environ["GITHUB_OAUTH_CLIENT_ID"],
                "client_secret": os.environ["GITHUB_OAUTH_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": f"{_app_base_url()}/api/integrations/github/callback",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def revoke_github_token(token: str) -> None:
    """Best-effort revocation via GitHub Apps API."""
    try:
        client_id = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "")
        client_secret = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.delete(
                f"https://api.github.com/applications/{client_id}/token",
                auth=(client_id, client_secret),
                json={"access_token": token},
            )
    except Exception as exc:
        logger.warning("GitHub token revocation failed (non-fatal): %s", exc)


@register
class GitHubConnector(BaseConnector):
    provider = "github"
    display_name = "GitHub"
    category = "code"
    description = "Issues, pull requests & repositories"
    auth_type = "oauth"
    available = True
    suggested_prompts = [
        "Which GitHub issues are open?",
        "Summarize recent pull requests",
        "What bugs are assigned to me on GitHub?",
    ]

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        if not self.is_connected:
            return []
        access_token = self.tokens.get("access_token")
        if not access_token:
            return []

        repos: list[str] = (
            self.integration.config.get("repos", []) if self.integration else []
        )
        if not repos:
            return []

        query_lower = query.lower()
        fetch_prs = any(
            re.search(rf"\b{re.escape(kw)}\b", query_lower) for kw in _GITHUB_PROVIDERS
        )
        endpoint_path = "pulls" if fetch_prs else "issues"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            for repo in repos[:3]:  # cap at 3 repos per query
                url = f"{GITHUB_API}/repos/{repo}/{endpoint_path}"
                try:
                    resp = await client.get(
                        url,
                        headers=headers,
                        params={"state": "open", "per_page": 20, "sort": "updated"},
                    )
                    if resp.status_code == 401:
                        logger.warning("GitHub token expired for repo %s", repo)
                        return records  # caller should trigger needs_reauth
                    resp.raise_for_status()
                    for item in resp.json():
                        num = item.get("number")
                        records.append(
                            {
                                "source": "github",
                                "citation_key": f"GitHub-{num}",
                                "number": num,
                                "title": item.get("title", ""),
                                "state": item.get("state", ""),
                                "url": item.get("html_url", ""),
                                "author": (item.get("user") or {}).get("login", ""),
                                "body_excerpt": (item.get("body") or "")[:300],
                            }
                        )
                except httpx.HTTPError as exc:
                    logger.warning("GitHub fetch error for %s: %s", repo, exc)

        return records
