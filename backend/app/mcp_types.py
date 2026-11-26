"""Shared type definitions for MCP client modules.

Both SqliteMcpClient and GithubMcpClient return this TypedDict from their
safe wrapper methods so callers can type-check a single consistent shape.
"""

from typing import Any, TypedDict


class McpToolResult(TypedDict):
    """Standardised result envelope returned by all *_safe_sync wrappers.

    ``success`` is True when the tool call completed without error.
    ``data``    holds the parsed response (list or dict); None on failure.
    ``error``   holds a prefixed error string on failure; None on success.
      - Timeout:  "[MCP_TIMEOUT] ..."
      - Other:    "[MCP_ERROR] ..."
    """

    success: bool
    data: Any | None
    error: str | None
