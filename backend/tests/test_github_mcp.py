import json
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

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

    # Bug 3 fix — whitespace-only token must be rejected
    def test_raises_if_token_is_whitespace_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
        with pytest.raises(GithubMcpClientError) as exc_info:
            GithubMcpClient(github_token="   ")
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" in str(exc_info.value)

    def test_strips_leading_trailing_whitespace_from_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
        client = GithubMcpClient(github_token="  valid_token  ")
        assert client.github_token == "valid_token"


class TestGithubMcpClientTools:
    # Bug 6 fix: correct return type annotation for yield fixture
    @pytest.fixture(autouse=True)
    def setup_mock_session(self) -> Generator[None, None, None]:
        # Bug 7 fix: patch via 'app.github_mcp_client.*' — the actual import path —
        # instead of 'backend.app.github_mcp_client.*', which required a fragile
        # sys.modules alias that mutated global state at import time.
        with patch("app.github_mcp_client.ClientSession") as mock_session_cls:
            self.mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__.return_value = self.mock_session
            yield

    @patch("app.github_mcp_client.stdio_client")
    def test_list_issues_returns_list(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        issues_data = [
            {"id": 1, "number": 101, "title": "First issue", "state": "open"},
            {"id": 2, "number": 102, "title": "Second issue", "state": "open"},
        ]
        self.mock_session.call_tool.return_value = SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text=json.dumps(issues_data))],
        )

        client = GithubMcpClient(github_token="test_token")
        result = client.list_issues_sync("owner", "repo")
        assert isinstance(result, list)
        assert result == issues_data

    @patch("app.github_mcp_client.stdio_client")
    def test_get_issue_returns_dict(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        issue_data = {"id": 1, "number": 101, "title": "Issue detail", "state": "open"}
        self.mock_session.call_tool.return_value = SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text=json.dumps(issue_data))],
        )

        client = GithubMcpClient(github_token="test_token")
        result = client.get_issue_sync("owner", "repo", 101)
        assert isinstance(result, dict)
        assert result == issue_data

    @patch("app.github_mcp_client.stdio_client")
    def test_list_pull_requests_returns_list(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        prs_data = [
            {"id": 10, "number": 201, "title": "Add feature X", "state": "open"},
            {"id": 11, "number": 202, "title": "Fix bug Y", "state": "open"},
        ]
        self.mock_session.call_tool.return_value = SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text=json.dumps(prs_data))],
        )

        client = GithubMcpClient(github_token="test_token")
        result = client.list_pull_requests_sync("owner", "repo")
        assert isinstance(result, list)
        assert result == prs_data

    @patch("app.github_mcp_client.stdio_client")
    def test_list_issues_wraps_exceptions(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        self.mock_session.call_tool.side_effect = RuntimeError("Subprocess communication failed")

        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.list_issues_sync("owner", "repo")
        assert "GitHub MCP list_issues failed" in str(exc_info.value)
        assert "RuntimeError" in str(exc_info.value)

    @patch("app.github_mcp_client.stdio_client")
    def test_list_issues_reraises_github_error(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        expected_error = GithubMcpClientError("Direct GitHub MCP error")
        self.mock_session.call_tool.side_effect = expected_error

        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.list_issues_sync("owner", "repo")
        assert exc_info.value is expected_error

    # Bug 1 fix — isError flag must surface as GithubMcpClientError
    @patch("app.github_mcp_client.stdio_client")
    def test_list_issues_raises_on_is_error_true(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        self.mock_session.call_tool.return_value = SimpleNamespace(
            isError=True,
            content=[SimpleNamespace(type="text", text="rate limit exceeded")],
        )

        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.list_issues_sync("owner", "repo")
        assert "rate limit exceeded" in str(exc_info.value)

    @patch("app.github_mcp_client.stdio_client")
    def test_get_issue_raises_on_is_error_true(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        self.mock_session.call_tool.return_value = SimpleNamespace(
            isError=True,
            content=[SimpleNamespace(type="text", text="repo not found")],
        )

        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.get_issue_sync("owner", "repo", 1)
        assert "repo not found" in str(exc_info.value)

    @patch("app.github_mcp_client.stdio_client")
    def test_list_pull_requests_raises_on_is_error_true(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        self.mock_session.call_tool.return_value = SimpleNamespace(
            isError=True,
            content=[SimpleNamespace(type="text", text="bad credentials")],
        )

        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.list_pull_requests_sync("owner", "repo")
        assert "bad credentials" in str(exc_info.value)

    # Bug 2 fix — error dict response must surface instead of returning []
    @patch("app.github_mcp_client.stdio_client")
    def test_list_issues_raises_on_error_dict_response(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        self.mock_session.call_tool.return_value = SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text=json.dumps({"error": "rate limited", "status": 429}))],
        )

        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.list_issues_sync("owner", "repo")
        assert "error response" in str(exc_info.value)

    @patch("app.github_mcp_client.stdio_client")
    def test_get_issue_raises_on_unexpected_list_response(self, mock_stdio: AsyncMock) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        self.mock_session.call_tool.return_value = SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text=json.dumps([{"id": 1}]))],
        )

        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.get_issue_sync("owner", "repo", 1)
        assert "list instead of a dict" in str(exc_info.value)


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


class TestStateValidation:
    # Bug 4 fix — invalid state values must be rejected locally
    def test_list_issues_rejects_invalid_state(self) -> None:
        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.list_issues_sync("owner", "repo", state="invalid")
        assert "Invalid state" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_list_pull_requests_rejects_invalid_state(self) -> None:
        client = GithubMcpClient(github_token="test_token")
        with pytest.raises(GithubMcpClientError) as exc_info:
            client.list_pull_requests_sync("owner", "repo", state="merged")
        assert "Invalid state" in str(exc_info.value)

    @pytest.mark.parametrize("state", ["open", "closed", "all"])
    @patch("app.github_mcp_client.stdio_client")
    @patch("app.github_mcp_client.ClientSession")
    def test_list_issues_accepts_valid_states(
        self, mock_cls: AsyncMock, mock_stdio: AsyncMock, state: str
    ) -> None:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        mock_session = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = mock_session
        mock_session.call_tool.return_value = SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(type="text", text="[]")],
        )

        client = GithubMcpClient(github_token="test_token")
        result = client.list_issues_sync("owner", "repo", state=state)
        assert result == []
