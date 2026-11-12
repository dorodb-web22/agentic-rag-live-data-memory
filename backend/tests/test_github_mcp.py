import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# Ensure both 'backend.app' and 'app' resolve to the same module
repo_root = str(Path(__file__).resolve().parent.parent.parent)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import app.github_mcp_client
import backend.app.github_mcp_client

sys.modules["backend.app.github_mcp_client"] = sys.modules["app.github_mcp_client"]

from app.github_mcp_client import GithubMcpClient, GithubMcpClientError


class TestGithubMcpClientInit:
    def test_raises_if_token_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
        with pytest.raises(GithubMcpClientError) as exc_info:
            GithubMcpClient()
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" in str(exc_info.value)

    def test_accepts_token_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "token_from_env")
        client = GithubMcpClient()
        assert client.github_token == "token_from_env"

    def test_accepts_token_as_argument(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "token_from_env")
        client = GithubMcpClient(github_token="tok_explicit")
        assert client.github_token == "tok_explicit"

    def test_accepts_repo_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        client = GithubMcpClient()
        assert client.github_repo == "owner/repo"


class TestGithubMcpClientTools:
    @pytest.fixture(autouse=True)
    def setup_mock_session(self) -> None:
        with patch("backend.app.github_mcp_client.ClientSession") as mock_session_cls:
            self.mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__.return_value = self.mock_session
            yield

    @patch("backend.app.github_mcp_client.stdio_client")
    def test_list_issues_returns_list(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        issues_data = [
            {"id": 1, "number": 101, "title": "First issue", "state": "open"},
            {"id": 2, "number": 102, "title": "Second issue", "state": "open"},
        ]
        self.mock_session.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(issues_data))]
        )

        client = GithubMcpClient(github_token="test_token")
        result = client.list_issues_sync("owner", "repo")
        assert isinstance(result, list)
        assert result == issues_data

    @patch("backend.app.github_mcp_client.stdio_client")
    def test_get_issue_returns_dict(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        issue_data = {"id": 1, "number": 101, "title": "Issue detail", "state": "open"}
        self.mock_session.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(issue_data))]
        )

        client = GithubMcpClient(github_token="test_token")
        result = client.get_issue_sync("owner", "repo", 101)
        assert isinstance(result, dict)
        assert result == issue_data

    @patch("backend.app.github_mcp_client.stdio_client")
    def test_list_pull_requests_returns_list(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        prs_data = [
            {"id": 10, "number": 201, "title": "Add feature X", "state": "open"},
            {"id": 11, "number": 202, "title": "Fix bug Y", "state": "open"},
        ]
        self.mock_session.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(prs_data))]
        )

        client = GithubMcpClient(github_token="test_token")
        result = client.list_pull_requests_sync("owner", "repo")
        assert isinstance(result, list)
        assert result == prs_data

    @patch("backend.app.github_mcp_client.stdio_client")
    def test_list_issues_wraps_exceptions(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        self.mock_session.call_tool.side_effect = RuntimeError("Subprocess communication failed")

        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.list_issues_sync("owner", "repo")
        assert "GitHub MCP list_issues failed" in str(exc_info.value)
        assert "RuntimeError" in str(exc_info.value)

    @patch("backend.app.github_mcp_client.stdio_client")
    def test_list_issues_reraises_github_error(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        expected_error = GithubMcpClientError("Direct GitHub MCP error")
        self.mock_session.call_tool.side_effect = expected_error

        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.list_issues_sync("owner", "repo")
        assert exc_info.value is expected_error


class TestBuildServerParams:
    def test_server_command_is_npx(self) -> None:
        client = GithubMcpClient(github_token="test_token")
        params = client._build_server_params()
        assert params.command == "npx"

    def test_server_args_include_package(self) -> None:
        client = GithubMcpClient(github_token="test_token")
        params = client._build_server_params()
        assert "-y" in params.args
        assert "@modelcontextprotocol/server-github" in params.args

    def test_server_env_contains_token(self) -> None:
        client = GithubMcpClient(github_token="test_token_secret")
        params = client._build_server_params()
        assert params.env["GITHUB_PERSONAL_ACCESS_TOKEN"] == client.github_token
