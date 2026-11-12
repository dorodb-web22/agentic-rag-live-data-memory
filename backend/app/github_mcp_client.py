import asyncio
import concurrent.futures
import json
import logging
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

_VALID_ISSUE_STATES = {"open", "closed", "all"}


def _run_coroutine(coro: Any) -> Any:
    """Run an async coroutine from either sync or async execution contexts.

    The official Model Context Protocol (MCP) SDK is built strictly async-first
    over asyncio stdio streams. This helper provides a safe bridge for synchronous
    execution contexts (such as standard LangGraph nodes or sync endpoint handlers)
    without causing nested event loop conflicts.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # get_running_loop() only succeeds when a loop is already running,
    # so loop.is_running() is always True here. We always use the thread pool.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class GithubMcpClientError(RuntimeError):
    """Raised when an error occurs during GitHub MCP operations."""


class GithubMcpClient:
    """Client for the official GitHub MCP server running over stdio via npx."""

    def __init__(
        self,
        github_token: str | None = None,
        github_repo: str | None = None,
    ) -> None:
        # Bug 3 fix: strip whitespace so "   " is treated as missing
        raw_token = github_token or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN") or ""
        self.github_token = raw_token.strip()
        if not self.github_token:
            raise GithubMcpClientError(
                "GITHUB_PERSONAL_ACCESS_TOKEN is not set. "
                "Export it in your environment before initializing GithubMcpClient."
            )

        self.github_repo = github_repo or os.getenv("GITHUB_REPO")
        # github_repo is optional — some tools operate repo-agnostically

    def _build_server_params(self) -> StdioServerParameters:
        """Build StdioServerParameters for the GitHub MCP server via npx."""
        return StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={
                **os.environ,
                "GITHUB_PERSONAL_ACCESS_TOKEN": self.github_token,
            },
        )

    def _check_tool_error(self, result: Any) -> None:
        """Raise GithubMcpClientError if the MCP server flagged a tool-level error.

        Bug 1 fix: CallToolResult.isError is set to True by the GitHub MCP server
        when the tool call itself fails (e.g. bad auth, 404, rate limit). Without
        this check the content text is parsed and silently returns [] / {}.
        """
        if getattr(result, "isError", False):
            error_text = next(
                (item.text for item in result.content if item.type == "text"),
                "Unknown GitHub MCP tool error",
            )
            raise GithubMcpClientError(f"GitHub MCP tool error: {error_text}")

    async def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
    ) -> list[dict[str, Any]]:
        """List issues for a GitHub repository via the MCP server."""
        # Bug 4 fix: validate state before making the remote call
        if state not in _VALID_ISSUE_STATES:
            raise GithubMcpClientError(
                f"Invalid state '{state}'. Must be one of: {_VALID_ISSUE_STATES}"
            )

        server_params = self._build_server_params()
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "list_issues",
                        arguments={"owner": owner, "repo": repo, "state": state},
                    )
                    # Bug 1 fix: surface tool-level errors instead of swallowing them
                    self._check_tool_error(result)
                    for item in result.content:
                        if item.type == "text":
                            data = self._parse_response(item.text)
                            # Bug 2 fix: raise on error dict instead of silently returning []
                            if isinstance(data, dict):
                                raise GithubMcpClientError(
                                    f"GitHub MCP list_issues returned an error response: {data}"
                                )
                            if isinstance(data, list):
                                return data
                    return []
        except GithubMcpClientError:
            raise
        except Exception as exc:
            logger.exception("GitHub MCP list_issues failed: %s", exc)
            raise GithubMcpClientError(
                f"GitHub MCP list_issues failed: {type(exc).__name__}"
            ) from exc

    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> dict[str, Any]:
        """Retrieve a single issue by number via the MCP server."""
        server_params = self._build_server_params()
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "get_issue",
                        arguments={"owner": owner, "repo": repo, "issue_number": issue_number},
                    )
                    # Bug 1 fix: surface tool-level errors
                    self._check_tool_error(result)
                    for item in result.content:
                        if item.type == "text":
                            data = self._parse_response(item.text)
                            # Bug 2 fix: a list is unexpected here — treat as error
                            if isinstance(data, list):
                                raise GithubMcpClientError(
                                    f"GitHub MCP get_issue returned a list instead of a dict: {data}"
                                )
                            if isinstance(data, dict):
                                return data
                    return {}
        except GithubMcpClientError:
            raise
        except Exception as exc:
            logger.exception("GitHub MCP get_issue failed: %s", exc)
            raise GithubMcpClientError(
                f"GitHub MCP get_issue failed: {type(exc).__name__}"
            ) from exc

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
    ) -> list[dict[str, Any]]:
        """List pull requests for a GitHub repository via the MCP server."""
        # Bug 4 fix: validate state before making the remote call
        if state not in _VALID_ISSUE_STATES:
            raise GithubMcpClientError(
                f"Invalid state '{state}'. Must be one of: {_VALID_ISSUE_STATES}"
            )

        server_params = self._build_server_params()
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "list_pull_requests",
                        arguments={"owner": owner, "repo": repo, "state": state},
                    )
                    # Bug 1 fix: surface tool-level errors
                    self._check_tool_error(result)
                    for item in result.content:
                        if item.type == "text":
                            data = self._parse_response(item.text)
                            # Bug 2 fix: raise on error dict instead of silently returning []
                            if isinstance(data, dict):
                                raise GithubMcpClientError(
                                    f"GitHub MCP list_pull_requests returned an error response: {data}"
                                )
                            if isinstance(data, list):
                                return data
                    return []
        except GithubMcpClientError:
            raise
        except Exception as exc:
            logger.exception("GitHub MCP list_pull_requests failed: %s", exc)
            raise GithubMcpClientError(
                f"GitHub MCP list_pull_requests failed: {type(exc).__name__}"
            ) from exc

    def _parse_response(self, raw_text: str) -> Any:
        """Safely parse JSON text returned by the GitHub MCP server."""
        cleaned = raw_text.strip()
        if not cleaned:
            return []
        try:
            return json.loads(cleaned)
        except Exception:
            return cleaned

    # Synchronous wrappers — safe to call from LangGraph nodes or sync handlers
    def list_issues_sync(self, owner: str, repo: str, state: str = "open") -> list[dict[str, Any]]:
        return _run_coroutine(self.list_issues(owner, repo, state))

    def get_issue_sync(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        return _run_coroutine(self.get_issue(owner, repo, issue_number))

    def list_pull_requests_sync(self, owner: str, repo: str, state: str = "open") -> list[dict[str, Any]]:
        return _run_coroutine(self.list_pull_requests(owner, repo, state))
