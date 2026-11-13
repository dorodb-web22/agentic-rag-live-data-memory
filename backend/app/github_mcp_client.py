import asyncio
import concurrent.futures
import json
import logging
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.mcp_types import McpToolResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 15.0
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


class GithubMcpTimeoutError(GithubMcpClientError):
    """Raised when a GitHub MCP operation exceeds the configured timeout."""


class GithubMcpClient:
    """Client for the official GitHub MCP server running over stdio via npx."""

    def __init__(
        self,
        github_token: str | None = None,
        github_repo: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        raw_token = github_token or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN") or ""
        self.github_token = raw_token.strip()
        if not self.github_token:
            raise GithubMcpClientError(
                "GITHUB_PERSONAL_ACCESS_TOKEN is not set. "
                "Export it in your environment before initializing GithubMcpClient."
            )

        self.github_repo = github_repo or os.getenv("GITHUB_REPO")
        # github_repo is optional — some tools operate repo-agnostically

        env_timeout = os.getenv("MCP_TIMEOUT_SECONDS")
        if timeout_seconds is not None:
            self.timeout_seconds = float(timeout_seconds)
        elif env_timeout:
            try:
                self.timeout_seconds = float(env_timeout)
            except ValueError:
                logger.warning(
                    "MCP_TIMEOUT_SECONDS='%s' is not a valid number; "
                    "falling back to default %.1fs.",
                    env_timeout,
                    DEFAULT_TIMEOUT_SECONDS,
                )
                self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        else:
            self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS

        # Bug B guard: a timeout of 0 or negative causes asyncio.wait_for to
        # cancel every coroutine immediately or raise deep inside asyncio.
        if self.timeout_seconds <= 0:
            raise GithubMcpClientError(
                f"timeout_seconds must be > 0, got {self.timeout_seconds}."
            )

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

        CallToolResult.isError is set to True by the GitHub MCP server
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
        if state not in _VALID_ISSUE_STATES:
            raise GithubMcpClientError(
                f"Invalid state '{state}'. Must be one of: {_VALID_ISSUE_STATES}"
            )

        server_params = self._build_server_params()

        async def _execute() -> list[dict[str, Any]]:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "list_issues",
                        arguments={"owner": owner, "repo": repo, "state": state},
                    )
                    self._check_tool_error(result)
                    for item in result.content:
                        if item.type == "text":
                            data = self._parse_response(item.text)
                            if isinstance(data, dict):
                                raise GithubMcpClientError(
                                    f"GitHub MCP list_issues returned an error response: {data}"
                                )
                            if isinstance(data, list):
                                return data
                    return []

        coro = _execute()
        try:
            return await asyncio.wait_for(coro, timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            # coro.close() is redundant in production (asyncio.wait_for wraps coro
            # in a Task that owns cleanup after cancellation), but is required when
            # asyncio.wait_for is mock-patched in tests to raise immediately without
            # consuming the coroutine — without it pytest emits RuntimeWarning.
            coro.close()
            logger.error("GitHub MCP list_issues timed out after %.1fs", self.timeout_seconds)
            raise GithubMcpTimeoutError(
                f"GitHub MCP list_issues timed out after {self.timeout_seconds}s."
            ) from exc
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

        async def _execute() -> dict[str, Any]:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "get_issue",
                        arguments={"owner": owner, "repo": repo, "issue_number": issue_number},
                    )
                    self._check_tool_error(result)
                    for item in result.content:
                        if item.type == "text":
                            data = self._parse_response(item.text)
                            if isinstance(data, list):
                                raise GithubMcpClientError(
                                    f"GitHub MCP get_issue returned a list instead of a dict: {data}"
                                )
                            if isinstance(data, dict):
                                return data
                    return {}

        coro = _execute()
        try:
            return await asyncio.wait_for(coro, timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            # coro.close() is redundant in production (asyncio.wait_for wraps coro
            # in a Task that owns cleanup after cancellation), but is required when
            # asyncio.wait_for is mock-patched in tests to raise immediately without
            # consuming the coroutine — without it pytest emits RuntimeWarning.
            coro.close()
            logger.error("GitHub MCP get_issue timed out after %.1fs", self.timeout_seconds)
            raise GithubMcpTimeoutError(
                f"GitHub MCP get_issue timed out after {self.timeout_seconds}s."
            ) from exc
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
        if state not in _VALID_ISSUE_STATES:
            raise GithubMcpClientError(
                f"Invalid state '{state}'. Must be one of: {_VALID_ISSUE_STATES}"
            )

        server_params = self._build_server_params()

        async def _execute() -> list[dict[str, Any]]:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "list_pull_requests",
                        arguments={"owner": owner, "repo": repo, "state": state},
                    )
                    self._check_tool_error(result)
                    for item in result.content:
                        if item.type == "text":
                            data = self._parse_response(item.text)
                            if isinstance(data, dict):
                                raise GithubMcpClientError(
                                    f"GitHub MCP list_pull_requests returned an error response: {data}"
                                )
                            if isinstance(data, list):
                                return data
                    return []

        coro = _execute()
        try:
            return await asyncio.wait_for(coro, timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            # coro.close() is redundant in production (asyncio.wait_for wraps coro
            # in a Task that owns cleanup after cancellation), but is required when
            # asyncio.wait_for is mock-patched in tests to raise immediately without
            # consuming the coroutine — without it pytest emits RuntimeWarning.
            coro.close()
            logger.error("GitHub MCP list_pull_requests timed out after %.1fs", self.timeout_seconds)
            raise GithubMcpTimeoutError(
                f"GitHub MCP list_pull_requests timed out after {self.timeout_seconds}s."
            ) from exc
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

    # Safe wrappers returning McpToolResult without raising exceptions
    def list_issues_safe_sync(
        self, owner: str, repo: str, state: str = "open"
    ) -> McpToolResult:
        """List issues returning a graceful McpToolResult instead of raising exceptions."""
        try:
            issues = self.list_issues_sync(owner, repo, state)
            return {"success": True, "data": issues, "error": None}
        except GithubMcpTimeoutError as exc:
            return {"success": False, "data": None, "error": f"[MCP_TIMEOUT] {str(exc)}"}
        except GithubMcpClientError as exc:
            return {"success": False, "data": None, "error": f"[MCP_ERROR] {str(exc)}"}
        except Exception as exc:
            logger.exception("Unexpected error in list_issues_safe_sync: %s", exc)
            return {"success": False, "data": None, "error": f"[MCP_ERROR] Unexpected {type(exc).__name__}"}

    def get_issue_safe_sync(
        self, owner: str, repo: str, issue_number: int
    ) -> McpToolResult:
        """Retrieve an issue returning a graceful McpToolResult instead of raising exceptions."""
        try:
            issue = self.get_issue_sync(owner, repo, issue_number)
            return {"success": True, "data": issue, "error": None}
        except GithubMcpTimeoutError as exc:
            return {"success": False, "data": None, "error": f"[MCP_TIMEOUT] {str(exc)}"}
        except GithubMcpClientError as exc:
            return {"success": False, "data": None, "error": f"[MCP_ERROR] {str(exc)}"}
        except Exception as exc:
            logger.exception("Unexpected error in get_issue_safe_sync: %s", exc)
            return {"success": False, "data": None, "error": f"[MCP_ERROR] Unexpected {type(exc).__name__}"}

    def list_pull_requests_safe_sync(
        self, owner: str, repo: str, state: str = "open"
    ) -> McpToolResult:
        """List pull requests returning a graceful McpToolResult instead of raising exceptions."""
        try:
            prs = self.list_pull_requests_sync(owner, repo, state)
            return {"success": True, "data": prs, "error": None}
        except GithubMcpTimeoutError as exc:
            return {"success": False, "data": None, "error": f"[MCP_TIMEOUT] {str(exc)}"}
        except GithubMcpClientError as exc:
            return {"success": False, "data": None, "error": f"[MCP_ERROR] {str(exc)}"}
        except Exception as exc:
            logger.exception("Unexpected error in list_pull_requests_safe_sync: %s", exc)
            return {"success": False, "data": None, "error": f"[MCP_ERROR] Unexpected {type(exc).__name__}"}
