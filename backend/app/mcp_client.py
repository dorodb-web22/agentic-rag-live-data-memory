import ast
import asyncio
import concurrent.futures
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, TypedDict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "demo.db"
DEFAULT_TIMEOUT_SECONDS = 15.0


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

    if loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return loop.run_until_complete(coro)


class McpClientError(RuntimeError):
    """Raised when an error occurs during MCP operations."""


class McpTimeoutError(McpClientError):
    """Raised when an MCP operation exceeds the configured timeout."""


class McpToolResult(TypedDict):
    success: bool
    data: Any | None
    error: str | None


class SqliteMcpClient:
    """Client for the official SQLite MCP server running over stdio."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        server_command: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        if db_path is None:
            env_path = os.getenv("SQLITE_DB_PATH")
            if env_path:
                db_path = Path(env_path)
                if not db_path.is_absolute():
                    db_path = Path(__file__).resolve().parent.parent / env_path
            else:
                db_path = DEFAULT_DB_PATH

        self.db_path = Path(db_path).resolve()
        self.server_command = server_command or self._resolve_server_command()

        env_timeout = os.getenv("MCP_TIMEOUT_SECONDS")
        if timeout_seconds is not None:
            self.timeout_seconds = float(timeout_seconds)
        elif env_timeout:
            self.timeout_seconds = float(env_timeout)
        else:
            self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    def _resolve_server_command(self) -> str:
        """Locate the mcp-server-sqlite binary."""
        env_cmd = os.getenv("MCP_SQLITE_SERVER_PATH")
        if env_cmd and os.path.exists(env_cmd):
            return env_cmd

        # Check virtualenv bin directory
        venv_bin = Path(sys.prefix) / "bin" / "mcp-server-sqlite"
        if venv_bin.exists():
            return str(venv_bin)

        # Fallback to system PATH
        discovered = shutil.which("mcp-server-sqlite")
        if discovered:
            return discovered

        return "mcp-server-sqlite"

    def _validate_safe_select(self, query: str) -> str:
        """Validate that the query is strictly a read-only SELECT statement."""
        normalized = query.strip()
        if not normalized:
            raise McpClientError("Query must not be empty.")

        # Reject query chaining and comment tricks
        if ";" in normalized.rstrip(";"):
            raise McpClientError("Security violation: Multiple statements or semicolons are not permitted.")

        if "--" in normalized or "/*" in normalized:
            raise McpClientError("Security violation: SQL comments are not permitted in queries.")

        # Must start with SELECT
        upper = normalized.upper()
        if not upper.startswith("SELECT"):
            raise McpClientError("Security violation: Only SELECT queries are permitted on the SQLite database.")

        # Disallow dangerous SQL keywords
        forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "ATTACH", "DETACH", "PRAGMA", "VACUUM")
        tokens = [t.strip("(),;") for t in upper.split()]
        for word in forbidden:
            if word in tokens:
                raise McpClientError(f"Security violation: Statement contains forbidden keyword '{word}'.")

        return normalized

    async def list_tables(self) -> list[str]:
        """Query the MCP server for available tables."""
        if not self.db_path.exists():
            raise McpClientError(f"SQLite database file not found at: {self.db_path}")

        server_params = StdioServerParameters(
            command=self.server_command,
            args=["--db-path", str(self.db_path)],
        )

        async def _execute() -> list[str]:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("list_tables", arguments={})
                    for item in result.content:
                        if item.type == "text":
                            data = self._parse_tool_output(item.text)
                            if isinstance(data, list):
                                return [row.get("name", "") for row in data if isinstance(row, dict)]
                    return []

        coro = _execute()
        try:
            return await asyncio.wait_for(coro, timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            coro.close()
            logger.error("SQLite MCP list_tables timed out after %.1fs", self.timeout_seconds)
            raise McpTimeoutError(f"SQLite MCP list_tables timed out after {self.timeout_seconds}s.") from exc
        except McpClientError:
            raise
        except Exception as exc:
            logger.exception("MCP list_tables failed: %s", exc)
            raise McpClientError(f"MCP list_tables failed: {type(exc).__name__}") from exc

    async def describe_table(self, table_name: str) -> list[dict[str, Any]]:
        """Query the MCP server for table schema information."""
        if not self.db_path.exists():
            raise McpClientError(f"SQLite database file not found at: {self.db_path}")

        server_params = StdioServerParameters(
            command=self.server_command,
            args=["--db-path", str(self.db_path)],
        )

        async def _execute() -> list[dict[str, Any]]:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "describe_table", arguments={"table_name": table_name}
                    )
                    for item in result.content:
                        if item.type == "text":
                            data = self._parse_tool_output(item.text)
                            if isinstance(data, list):
                                return data
                    return []

        coro = _execute()
        try:
            return await asyncio.wait_for(coro, timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            coro.close()
            logger.error("SQLite MCP describe_table timed out after %.1fs", self.timeout_seconds)
            raise McpTimeoutError(f"SQLite MCP describe_table timed out after {self.timeout_seconds}s.") from exc
        except McpClientError:
            raise
        except Exception as exc:
            logger.exception("MCP describe_table failed: %s", exc)
            raise McpClientError(f"MCP describe_table failed: {type(exc).__name__}") from exc

    async def read_query(self, query: str) -> list[dict[str, Any]]:
        """Execute a safe read-only query using the MCP server's read_query tool."""
        if not self.db_path.exists():
            raise McpClientError(f"SQLite database file not found at: {self.db_path}")

        safe_query = self._validate_safe_select(query)

        server_params = StdioServerParameters(
            command=self.server_command,
            args=["--db-path", str(self.db_path)],
        )

        async def _execute() -> list[dict[str, Any]]:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "read_query", arguments={"query": safe_query}
                    )
                    for item in result.content:
                        if item.type == "text":
                            text = item.text.strip()
                            if text.startswith("Database error:") or text.startswith("Error:"):
                                raise McpClientError(text)
                            data = self._parse_tool_output(text)
                            if isinstance(data, list):
                                return data
                            return [{"raw_result": data}]
                    return []

        coro = _execute()
        try:
            return await asyncio.wait_for(coro, timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            coro.close()
            logger.error("SQLite MCP read_query timed out after %.1fs", self.timeout_seconds)
            raise McpTimeoutError(f"SQLite MCP read_query timed out after {self.timeout_seconds}s.") from exc
        except McpClientError:
            raise
        except Exception as exc:
            logger.exception("MCP read_query failed: %s", exc)
            raise McpClientError(f"MCP read_query failed: {type(exc).__name__}") from exc

    def _parse_tool_output(self, raw_text: str) -> Any:
        """Safely parse text returned by mcp-server-sqlite."""
        cleaned = raw_text.strip()
        if not cleaned or cleaned == "[]":
            return []
        try:
            return json.loads(cleaned)
        except Exception:
            try:
                return ast.literal_eval(cleaned)
            except Exception:
                return cleaned

    # Synchronous helper methods for seamless agent execution
    def get_tables_sync(self) -> list[str]:
        return _run_coroutine(self.list_tables())

    def describe_table_sync(self, table_name: str) -> list[dict[str, Any]]:
        return _run_coroutine(self.describe_table(table_name))

    def execute_query_sync(self, query: str) -> list[dict[str, Any]]:
        return _run_coroutine(self.read_query(query))

    # Safe wrappers returning McpToolResult without raising exceptions
    def execute_query_safe_sync(self, query: str) -> McpToolResult:
        """Execute a query returning a graceful McpToolResult instead of raising exceptions.

        Safe to call from LangGraph nodes without crashing the state machine.
        """
        try:
            records = self.execute_query_sync(query)
            return {"success": True, "data": records, "error": None}
        except McpTimeoutError as exc:
            return {"success": False, "data": None, "error": f"[MCP_TIMEOUT] {str(exc)}"}
        except McpClientError as exc:
            return {"success": False, "data": None, "error": f"[MCP_ERROR] {str(exc)}"}
        except Exception as exc:
            logger.exception("Unexpected error in execute_query_safe_sync: %s", exc)
            return {"success": False, "data": None, "error": f"[MCP_ERROR] Unexpected {type(exc).__name__}"}

    def get_tables_safe_sync(self) -> McpToolResult:
        """Query available tables returning a graceful McpToolResult."""
        try:
            tables = self.get_tables_sync()
            return {"success": True, "data": tables, "error": None}
        except McpTimeoutError as exc:
            return {"success": False, "data": None, "error": f"[MCP_TIMEOUT] {str(exc)}"}
        except McpClientError as exc:
            return {"success": False, "data": None, "error": f"[MCP_ERROR] {str(exc)}"}
        except Exception as exc:
            logger.exception("Unexpected error in get_tables_safe_sync: %s", exc)
            return {"success": False, "data": None, "error": f"[MCP_ERROR] Unexpected {type(exc).__name__}"}

    def describe_table_safe_sync(self, table_name: str) -> McpToolResult:
        """Query table schema information returning a graceful McpToolResult."""
        try:
            schema = self.describe_table_sync(table_name)
            return {"success": True, "data": schema, "error": None}
        except McpTimeoutError as exc:
            return {"success": False, "data": None, "error": f"[MCP_TIMEOUT] {str(exc)}"}
        except McpClientError as exc:
            return {"success": False, "data": None, "error": f"[MCP_ERROR] {str(exc)}"}
        except Exception as exc:
            logger.exception("Unexpected error in describe_table_safe_sync: %s", exc)
            return {"success": False, "data": None, "error": f"[MCP_ERROR] Unexpected {type(exc).__name__}"}
