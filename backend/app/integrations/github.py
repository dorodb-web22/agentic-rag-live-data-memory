"""GitHub connector — read-only OAuth: issues, PRs, commits, and repositories.

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

_PR_KEYWORDS = {"pull request", "pull requests", "pr", "prs", "merge", "merged"}
_COMMIT_KEYWORDS = {"commit", "commits", "history", "pushed"}
_GITHUB_URL_RE = re.compile(
    r"github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+?)(?:\.git)?(?:[/?#\s]|$)",
    re.IGNORECASE,
)
_SAFE_REPO_RE = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")


def _app_base_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def _extract_repos_from_query(query: str) -> list[str]:
    """Extract explicit `owner/repo` slugs from GitHub URLs mentioned in *query*."""
    found: list[str] = []
    for match in _GITHUB_URL_RE.finditer(query or ""):
        slug = match.group(1).strip("/")
        if slug.endswith(".git"):
            slug = slug[:-4]
        if _SAFE_REPO_RE.match(slug) and slug not in found:
            found.append(slug)
    return found


def build_github_auth_url(state: str) -> str:
    params = {
        "client_id": os.environ["GITHUB_OAUTH_CLIENT_ID"],
        "redirect_uri": f"{_app_base_url()}/api/integrations/github/callback",
        "scope": "repo",  # read-only repos, issues, PRs, commits
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


async def _discover_user_repos(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    limit: int = 3,
) -> list[str]:
    """Auto-discover the authenticated user's most recently updated repos."""
    try:
        resp = await client.get(
            f"{GITHUB_API}/user/repos",
            headers=headers,
            params={
                "sort": "updated",
                "per_page": max(limit, 5),
                "affiliation": "owner,collaborator,organization_member",
            },
        )
        if resp.status_code == 401:
            logger.warning("GitHub token expired during repo auto-discovery")
            return []
        resp.raise_for_status()
        discovered: list[str] = []
        for item in resp.json():
            full_name = str(item.get("full_name") or "").strip()
            if _SAFE_REPO_RE.match(full_name) and full_name not in discovered:
                discovered.append(full_name)
                if len(discovered) >= limit:
                    break
        return discovered
    except httpx.HTTPError as exc:
        logger.warning("GitHub repo auto-discovery failed: %s", exc)
        return []


@register
class GitHubConnector(BaseConnector):
    provider = "github"
    display_name = "GitHub"
    category = "code"
    description = "Issues, pull requests, commits & repositories"
    auth_type = "oauth"
    available = True
    suggested_prompts = [
        "Which GitHub issues are open?",
        "Summarize recent pull requests",
        "Show the latest commits in my repository",
    ]

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        if not self.is_connected:
            return []
        access_token = self.tokens.get("access_token")
        if not access_token:
            return []

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        query_lower = (query or "").lower()
        fetch_commits = any(
            re.search(rf"\b{re.escape(kw)}\b", query_lower) for kw in _COMMIT_KEYWORDS
        )
        fetch_prs = not fetch_commits and any(
            re.search(rf"\b{re.escape(kw)}\b", query_lower) for kw in _PR_KEYWORDS
        )

        # Priority: explicit GitHub URL in query -> user-configured repos -> auto-discovered repos
        url_repos = _extract_repos_from_query(query)
        configured_repos: list[str] = [
            r.strip()
            for r in (self.integration.config.get("repos", []) if self.integration else [])
            if isinstance(r, str) and _SAFE_REPO_RE.match(r.strip())
        ]

        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=10.0) as client:
            repos: list[str] = []
            for r in url_repos + configured_repos:
                if r not in repos:
                    repos.append(r)
            if not repos:
                repos = await _discover_user_repos(client, headers, limit=3)
            if not repos:
                return []

            for repo in repos[:3]:  # cap at 3 repos per query
                if fetch_commits:
                    await self._fetch_repo_commits(client, headers, repo, records)
                elif fetch_prs:
                    await self._fetch_repo_pulls(client, headers, repo, query_lower, records)
                else:
                    await self._fetch_repo_issues(client, headers, repo, records)

        return records

    async def _fetch_repo_commits(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        repo: str,
        records: list[dict[str, Any]],
    ) -> None:
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/commits",
                headers=headers,
                params={"per_page": 20},
            )
            if resp.status_code == 401:
                logger.warning("GitHub token expired for repo %s", repo)
                return
            resp.raise_for_status()
            for item in resp.json():
                sha = str(item.get("sha") or "")
                short_sha = sha[:7] or "unknown"
                commit_obj = item.get("commit") or {}
                message = str(commit_obj.get("message") or "").strip()
                first_line = message.splitlines()[0] if message else "(no message)"
                author_info = commit_obj.get("author") or {}
                author_login = (item.get("author") or {}).get("login") or author_info.get("name", "")
                records.append(
                    {
                        "source": "github",
                        "citation_key": f"GitHub-{short_sha}",
                        "sha": short_sha,
                        "repo": repo,
                        "title": first_line,
                        "state": "committed",
                        "url": item.get("html_url", ""),
                        "author": author_login,
                        "date": author_info.get("date", ""),
                        "body_excerpt": message[:300],
                    }
                )
        except httpx.HTTPError as exc:
            logger.warning("GitHub commits fetch error for %s: %s", repo, exc)

    async def _fetch_repo_pulls(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        repo: str,
        query_lower: str,
        records: list[dict[str, Any]],
    ) -> None:
        wants_all = any(w in query_lower for w in ("recent", "latest", "merged", "closed", "all", "new", "last"))
        state = "all" if wants_all else "open"
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/pulls",
                headers=headers,
                params={"state": state, "per_page": 20, "sort": "updated", "direction": "desc"},
            )
            if resp.status_code == 401:
                logger.warning("GitHub token expired for repo %s", repo)
                return
            resp.raise_for_status()
            items = resp.json()
            # If open-only returned nothing, fall back to recent closed/merged PRs
            if not items and state == "open":
                resp2 = await client.get(
                    f"{GITHUB_API}/repos/{repo}/pulls",
                    headers=headers,
                    params={"state": "all", "per_page": 10, "sort": "updated", "direction": "desc"},
                )
                if resp2.status_code == 200:
                    items = resp2.json()
            for item in items:
                num = item.get("number")
                records.append(
                    {
                        "source": "github",
                        "citation_key": f"GitHub-{num}",
                        "number": num,
                        "repo": repo,
                        "title": item.get("title", ""),
                        "state": "merged" if item.get("merged_at") else item.get("state", ""),
                        "url": item.get("html_url", ""),
                        "author": (item.get("user") or {}).get("login", ""),
                        "body_excerpt": (item.get("body") or "")[:300],
                    }
                )
        except httpx.HTTPError as exc:
            logger.warning("GitHub pulls fetch error for %s: %s", repo, exc)

    async def _fetch_repo_issues(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        repo: str,
        records: list[dict[str, Any]],
    ) -> None:
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo}/issues",
                headers=headers,
                params={"state": "open", "per_page": 20, "sort": "updated"},
            )
            if resp.status_code == 401:
                logger.warning("GitHub token expired for repo %s", repo)
                return
            resp.raise_for_status()
            for item in resp.json():
                num = item.get("number")
                records.append(
                    {
                        "source": "github",
                        "citation_key": f"GitHub-{num}",
                        "number": num,
                        "repo": repo,
                        "title": item.get("title", ""),
                        "state": item.get("state", ""),
                        "url": item.get("html_url", ""),
                        "author": (item.get("user") or {}).get("login", ""),
                        "body_excerpt": (item.get("body") or "")[:300],
                    }
                )
        except httpx.HTTPError as exc:
            logger.warning("GitHub issues fetch error for %s: %s", repo, exc)
