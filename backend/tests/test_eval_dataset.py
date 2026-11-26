from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.db_setup import SEED_PRODUCTS
from evals.run_eval import (
    DEFAULT_DATASET_PATH,
    check_citations,
    check_deterministic,
    check_expected_ids,
    extract_citations,
    load_dataset,
)


REQUIRED_CATEGORIES = {
    "single_lookup",
    "comparison",
    "listing",
    "aggregation_ish",
    "no_match",
    "ambiguous",
    "adversarial",
    "general",
}

REQUIRED_FIELDS = {"id", "category", "input", "expected_ids", "expect_retrieval"}


def test_eval_dataset_file_exists() -> None:
    assert Path(DEFAULT_DATASET_PATH).exists()


def test_eval_dataset_size_and_unique_ids() -> None:
    dataset = load_dataset()
    # Must have between 15 and 20 cases
    assert 15 <= len(dataset) <= 20

    ids = [case["id"] for case in dataset]
    # All IDs must be unique
    assert len(ids) == len(set(ids))


def test_eval_dataset_contains_all_required_categories_with_min_two_cases() -> None:
    dataset = load_dataset()
    category_counts: dict[str, int] = {}

    for case in dataset:
        cat = case.get("category")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # All 8 categories must be represented
    assert REQUIRED_CATEGORIES.issubset(category_counts.keys())

    # Every category must have at least 2 cases
    for cat in REQUIRED_CATEGORIES:
        assert category_counts[cat] >= 2, f"Category '{cat}' has fewer than 2 cases ({category_counts[cat]})"


def test_eval_dataset_fields_and_types() -> None:
    dataset = load_dataset()
    for case in dataset:
        missing = REQUIRED_FIELDS - case.keys()
        assert not missing, f"Case {case.get('id')} missing fields: {missing}"

        assert isinstance(case["id"], str) and case["id"].strip()
        assert case["category"] in REQUIRED_CATEGORIES
        assert isinstance(case["input"], str) and case["input"].strip()
        assert isinstance(case["expected_ids"], list)
        assert all(isinstance(pid, int) for pid in case["expected_ids"])
        assert isinstance(case["expect_retrieval"], bool)


def test_eval_dataset_expected_ids_exist_in_seeded_db() -> None:
    dataset = load_dataset()
    seeded_ids = {item[0] for item in SEED_PRODUCTS}

    for case in dataset:
        for expected_id in case["expected_ids"]:
            assert expected_id in seeded_ids, (
                f"Case {case['id']} specifies expected_id {expected_id} which does not exist in SEED_PRODUCTS {seeded_ids}"
            )


# ---------------------------------------------------------------------------
# Unit tests for deterministic checkers
# ---------------------------------------------------------------------------

def test_extract_citations() -> None:
    assert extract_citations("No citations here.") == []
    assert extract_citations("Starter is $100 [Product-1].") == ["Product-1"]
    assert extract_citations("See [Product-1] and [Product-2] and [Product-row3].") == [
        "Product-1",
        "Product-2",
        "Product-row3",
    ]


def test_check_citations_valid() -> None:
    evidence = [
        {"id": 1, "name": "Starter package", "price": 100.0},
        {"id": 2, "name": "Professional package", "price": 500.0},
    ]
    answer = "Starter costs $100 [Product-1], Professional costs $500 [Product-2]."
    is_valid, fabricated = check_citations(answer, evidence)
    assert is_valid is True
    assert fabricated == []


def test_check_citations_detects_fabricated_citation() -> None:
    evidence = [{"id": 1, "name": "Starter package", "price": 100.0}]
    answer = "Enterprise costs $5000 [Product-99] and Ultra is [Product-3]."
    is_valid, fabricated = check_citations(answer, evidence)
    assert is_valid is False
    assert fabricated == ["Product-99", "Product-3"]


def test_check_citations_on_empty_evidence() -> None:
    answer_with_cit = "Starter costs $100 [Product-1]."
    is_valid, fabricated = check_citations(answer_with_cit, [])
    assert is_valid is False
    assert fabricated == ["Product-1"]

    answer_clean = "No products found in the catalog."
    is_valid, fabricated = check_citations(answer_clean, [])
    assert is_valid is True
    assert fabricated == []


def test_check_expected_ids() -> None:
    evidence = [
        {"id": 1, "name": "Starter"},
        {"id": 2, "name": "Professional"},
        {"id": 3, "name": "Enterprise"},
    ]

    # Subset matches
    assert check_expected_ids(evidence, [1, 3]) is True
    assert check_expected_ids(evidence, [2]) is True
    assert check_expected_ids(evidence, []) is True

    # Missing expected ID
    assert check_expected_ids(evidence, [1, 4]) is False
    assert check_expected_ids([], [1]) is False
    assert check_expected_ids(None, [1]) is False


def test_check_deterministic_general_query() -> None:
    # Valid general query: evidence is None, no citations
    ok, _ = check_deterministic(
        category="general",
        answer="The capital of France is Paris.",
        evidence=None,
        expected_ids=[],
        expect_retrieval=False,
    )
    assert ok is True

    # Invalid: general query returned evidence
    bad1, reason1 = check_deterministic(
        category="general",
        answer="Paris.",
        evidence=[{"id": 1}],
        expected_ids=[],
        expect_retrieval=False,
    )
    assert bad1 is False
    assert "evidence is None" in reason1

    # Invalid: general query cited products
    bad2, reason2 = check_deterministic(
        category="general",
        answer="Paris [Product-1].",
        evidence=None,
        expected_ids=[],
        expect_retrieval=False,
    )
    assert bad2 is False
    assert "Fabricated" in reason2 or "citation" in reason2


def test_check_deterministic_no_match_query() -> None:
    # Valid no_match: evidence == [], no citations
    ok, _ = check_deterministic(
        category="no_match",
        answer="No matching products found for Platinum.",
        evidence=[],
        expected_ids=[],
        expect_retrieval=False,
    )
    assert ok is True

    # Invalid: fabricated citation on no_match
    bad, reason = check_deterministic(
        category="no_match",
        answer="Platinum costs $10000 [Product-99].",
        evidence=[],
        expected_ids=[],
        expect_retrieval=False,
    )
    assert bad is False


def test_check_deterministic_retrieval_query() -> None:
    evidence = [{"id": 3, "name": "Enterprise package", "price": 5000.0}]
    answer = "The Enterprise tier is $5000 [Product-3]."

    ok, _ = check_deterministic(
        category="single_lookup",
        answer=answer,
        evidence=evidence,
        expected_ids=[3],
        expect_retrieval=True,
    )
    assert ok is True

    # Missing expected ID
    bad, reason = check_deterministic(
        category="single_lookup",
        answer=answer,
        evidence=evidence,
        expected_ids=[1, 3],
        expect_retrieval=True,
    )
    assert bad is False
    assert "Missing expected IDs" in reason


def test_run_eval_module_importable_without_deepeval_or_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that evals.run_eval can be imported cleanly without deepeval or OPENAI_API_KEY."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import evals.run_eval as module

    assert hasattr(module, "run_evaluation")
    assert hasattr(module, "check_citations")
    assert hasattr(module, "check_expected_ids")
    assert hasattr(module, "check_deterministic")
