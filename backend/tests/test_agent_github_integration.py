from typing import Any

from langchain_core.messages import AIMessage
import pytest

from app.agent import (
    BasicAgent,
    _build_citation_index,
    _validate_citations,
    create_agent_graph,
    is_github_query,
    planner_node,
)


class RecordingFakeLLM:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.invocations: list[Any] = []

    def invoke(self, messages: Any) -> AIMessage:
        self.invocations.append(messages)
        return AIMessage(content=self.answer)


class MockGithubClient:
    def __init__(self, issues: list[dict[str, Any]] | None = None, prs: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or [
            {"number": 19, "title": "Fix thread concurrency race", "state": "open"},
            {"number": 20, "title": "Wire GitHub MCP client into agent", "state": "open"},
        ]
        self.prs = prs or [
            {"number": 27, "title": "fix: retrieval and routing", "state": "open"},
        ]
        self.issues_calls: int = 0
        self.prs_calls: int = 0

    def list_issues_safe_sync(self, owner: str, repo: str, state: str = "open") -> dict[str, Any]:
        self.issues_calls += 1
        return {"success": True, "data": self.issues, "error": None}

    def list_pull_requests_safe_sync(self, owner: str, repo: str, state: str = "open") -> dict[str, Any]:
        self.prs_calls += 1
        return {"success": True, "data": self.prs, "error": None}


@pytest.mark.parametrize(
    "query",
    [
        "Which GitHub issues are open?",
        "Are there any open pull requests?",
        "Show me open PRs in the repository",
        "List all bugs reported on github",
        "Check commits on the repo",
    ],
)
def test_planner_routes_to_github_plan(query: str) -> None:
    plan = planner_node({"query": query})
    assert plan["plan"] == "github"
    assert plan["sql"] is None


def test_github_citation_indexing_and_validation() -> None:
    records = [
        {"number": 19, "title": "Fix concurrency"},
        {"number": 20, "title": "Wire GitHub client"},
    ]
    index = _build_citation_index(records)
    assert "GitHub-19" in index
    assert "GitHub-20" in index

    raw_answer = "We fixed concurrency in [GitHub-19] and made up [GitHub-999] for fun."
    validated = _validate_citations(raw_answer, records)
    assert "[GitHub-19]" in validated
    assert "[GitHub-999]" not in validated


def test_agent_github_integration_with_mock_client() -> None:
    mock_gh = MockGithubClient()
    fake_llm = RecordingFakeLLM(
        "Open issues include thread race [GitHub-19] and client integration [GitHub-20]."
    )
    graph = create_agent_graph(llm=fake_llm, github_client=mock_gh)
    agent = BasicAgent(graph=graph, github_client=mock_gh)

    answer, evidence = agent.query_with_evidence("What GitHub issues are currently open?")
    assert "[GitHub-19]" in answer
    assert "[GitHub-20]" in answer
    assert evidence is not None
    assert len(evidence) == 2
    assert evidence[0]["number"] == 19


def test_agent_github_unconfigured_token_graceful_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_PERSONAL_ACCESS_TOKEN", raising=False)
    fake_llm = RecordingFakeLLM("Please set GITHUB_PERSONAL_ACCESS_TOKEN to enable live GitHub search.")
    graph = create_agent_graph(llm=fake_llm, github_client=None)
    agent = BasicAgent(graph=graph)

    answer, evidence = agent.query_with_evidence("What PRs are open on GitHub?")
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in answer
    assert evidence is None


@pytest.mark.parametrize(
    "query, expected_plan",
    [
        ("How can we improve our team productivity?", "general"),
        ("What is the best approach to learning Python?", "general"),
        ("What is the price of the Enterprise package?", "db"),
        ("Give me a comprehensive overview of our subscription plans", "db"),
    ],
)
def test_pr_substring_words_do_not_false_positive_to_github(
    query: str, expected_plan: str
) -> None:
    assert is_github_query(query) is False
    plan = planner_node({"query": query})
    assert plan["plan"] == expected_plan


def test_worker_pr_word_boundary_does_not_misroute_issues_query() -> None:
    mock_gh = MockGithubClient()
    fake_llm = RecordingFakeLLM("Open issue [GitHub-19].")
    graph = create_agent_graph(llm=fake_llm, github_client=mock_gh)
    agent = BasicAgent(graph=graph, github_client=mock_gh)

    # Contains "comprehensive", "improve", "enterprise", "approach" (all contain "pr" substring)
    answer, evidence = agent.query_with_evidence(
        "Give a comprehensive list of open GitHub issues to improve our enterprise approach"
    )
    assert "[GitHub-19]" in answer
    assert evidence is not None
    assert mock_gh.issues_calls == 1
    assert mock_gh.prs_calls == 0


def test_worker_routes_pr_query_to_pull_requests() -> None:
    mock_gh = MockGithubClient()
    fake_llm = RecordingFakeLLM("Open PR [GitHub-27].")
    graph = create_agent_graph(llm=fake_llm, github_client=mock_gh)
    agent = BasicAgent(graph=graph, github_client=mock_gh)

    answer, evidence = agent.query_with_evidence("Show open PRs on GitHub")
    assert "[GitHub-27]" in answer
    assert evidence is not None
    assert mock_gh.prs_calls == 1
    assert mock_gh.issues_calls == 0

