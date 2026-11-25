"""DeepEval faithfulness evaluation runner for Agentic RAG answers.

Evaluates adherence of agent answers to raw MCP JSON evidence retrieved from
the database, checking for zero fabricated citations and faithfulness threshold >= 0.8.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import re
import sys
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "dataset.json"
DEFAULT_RESULTS_PATH = Path(__file__).resolve().parent / "results.json"
DEFAULT_JUDGE_MODEL = os.getenv("DEEPEVAL_JUDGE_MODEL", "gpt-4o-mini")
DEFAULT_THRESHOLD = 0.8


def load_dataset(dataset_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load the evaluation dataset JSON file."""
    path = Path(dataset_path or DEFAULT_DATASET_PATH).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Evaluation dataset not found at: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Dataset root must be a list of cases, got {type(data).__name__}.")
    return data


def extract_citations(answer: str) -> list[str]:
    """Extract all inline citation tags (e.g. 'Product-1', 'Product-row0') from text."""
    if not isinstance(answer, str):
        return []
    return re.findall(r"\[(Product-[^\]]+)\]", answer)


def check_citations(
    answer: str,
    evidence: list[dict[str, Any]] | None,
) -> tuple[bool, list[str]]:
    """Verify that every citation in answer references an existing item in evidence.

    Returns:
        (is_valid, list_of_fabricated_citations)
    """
    citations = extract_citations(answer)
    if not citations:
        return True, []

    if not evidence:
        return False, citations

    valid_keys: set[str] = set()
    for idx, record in enumerate(evidence):
        if isinstance(record, dict):
            if "id" in record:
                valid_keys.add(f"Product-{record['id']}")
            valid_keys.add(f"Product-row{idx}")

    fabricated = [c for c in citations if c not in valid_keys]
    return len(fabricated) == 0, fabricated


def check_expected_ids(
    evidence: list[dict[str, Any]] | None,
    expected_ids: list[int],
) -> bool:
    """Verify that all expected product IDs are present in the retrieved evidence."""
    if not expected_ids:
        return True
    if not evidence:
        return False

    retrieved_ids = {
        r["id"]
        for r in evidence
        if isinstance(r, dict) and "id" in r and isinstance(r["id"], int)
    }
    return set(expected_ids).issubset(retrieved_ids)


def check_deterministic(
    category: str,
    answer: str,
    evidence: list[dict[str, Any]] | None,
    expected_ids: list[int],
    expect_retrieval: bool,
) -> tuple[bool, str]:
    """Execute cheap deterministic validation rules for a test case."""
    # Rule 1: Zero fabricated citations across all categories
    valid_citations, fabricated = check_citations(answer, evidence)
    if not valid_citations:
        return False, f"Fabricated citations found in answer: {fabricated}"

    # Rule 2: General queries must not retrieve evidence or cite products
    if category == "general":
        if evidence is not None:
            return False, f"Expected evidence is None for general query, got {evidence}"
        if extract_citations(answer):
            return False, "General query answer contains citation markers"
        return True, "General query correctly bypassed retrieval and citations"

    # Rule 3: No-match queries must retrieve an empty list and cite no products
    if category == "no_match":
        if evidence != []:
            return False, f"Expected evidence == [] for no_match query, got {evidence}"
        if extract_citations(answer):
            return False, "No-match answer contains citation markers for non-existent product"
        return True, "No-match query returned empty evidence and zero citations"

    # Rule 4: Queries expecting retrieval must return non-empty evidence containing all expected_ids
    if expect_retrieval:
        if not evidence:
            return False, "Expected non-empty evidence, but got None or []"
        if not check_expected_ids(evidence, expected_ids):
            retrieved_ids = [r.get("id") for r in evidence if isinstance(r, dict)]
            return False, f"Missing expected IDs {expected_ids}; retrieved: {retrieved_ids}"
        return True, "Deterministic retrieval checks passed"

    # Rule 5: Queries not expecting retrieval (e.g. adversarial SQL injections)
    return True, "Deterministic checks passed"


def evaluate_faithfulness_with_deepeval(
    input_query: str,
    answer: str,
    evidence: list[dict[str, Any]],
    model: str,
    threshold: float,
) -> tuple[float, str, bool]:
    """Run DeepEval FaithfulnessMetric on answer against raw MCP JSON evidence."""
    try:
        from deepeval.metrics import FaithfulnessMetric
        from deepeval.test_case import LLMTestCase
    except ImportError as exc:
        raise RuntimeError(
            "DeepEval is required to run the faithfulness LLM judge. "
            "Install with: pip install -e .[eval]"
        ) from exc

    retrieval_context = [json.dumps(record) for record in evidence]
    test_case = LLMTestCase(
        input=input_query,
        actual_output=answer,
        retrieval_context=retrieval_context,
    )
    metric = FaithfulnessMetric(
        threshold=threshold,
        model=model,
        include_reason=True,
    )
    metric.measure(test_case)
    return float(metric.score), str(metric.reason or ""), bool(metric.is_successful())


def run_case(
    agent: Any,
    case: dict[str, Any],
    judge_model: str = DEFAULT_JUDGE_MODEL,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """Execute and evaluate a single dataset case."""
    case_id = case["id"]
    category = case["category"]
    input_query = case["input"]
    expected_ids = case.get("expected_ids", [])
    expect_retrieval = case.get("expect_retrieval", True)

    answer: str = ""
    evidence: list[dict[str, Any]] | None = None
    error_message: str | None = None

    try:
        answer, evidence = agent.query_with_evidence(input_query)
    except Exception as exc:
        logger.exception("Case %s raised an exception during agent execution", case_id)
        error_message = f"{type(exc).__name__}: {exc}"

    if error_message is not None:
        return {
            "id": case_id,
            "category": category,
            "input": input_query,
            "answer": answer,
            "evidence": evidence,
            "expected_ids": expected_ids,
            "expect_retrieval": expect_retrieval,
            "deterministic_passed": False,
            "deterministic_reason": f"Agent execution failed: {error_message}",
            "faithfulness_score": 0.0,
            "faithfulness_reason": f"Agent execution error: {error_message}",
            "fabricated_citations": [],
            "passed": False,
            "error": error_message,
        }

    # Deterministic checks
    det_passed, det_reason = check_deterministic(
        category=category,
        answer=answer,
        evidence=evidence,
        expected_ids=expected_ids,
        expect_retrieval=expect_retrieval,
    )
    _, fabricated = check_citations(answer, evidence)

    # Faithfulness check: run DeepEval judge when retrieval context exists
    if expect_retrieval and evidence:
        try:
            score, reason, faith_passed = evaluate_faithfulness_with_deepeval(
                input_query=input_query,
                answer=answer,
                evidence=evidence,
                model=judge_model,
                threshold=threshold,
            )
        except Exception as exc:
            score = 0.0
            reason = f"Faithfulness evaluation error: {type(exc).__name__}: {exc}"
            faith_passed = False
    else:
        # Cases with no retrieval context (general / no_match) rely on deterministic ground truth
        score = 1.0 if det_passed else 0.0
        reason = f"Skipped LLM judge (no retrieval context): {det_reason}"
        faith_passed = det_passed

    case_passed = bool(det_passed and faith_passed and len(fabricated) == 0)

    return {
        "id": case_id,
        "category": category,
        "input": input_query,
        "answer": answer,
        "evidence": evidence,
        "expected_ids": expected_ids,
        "expect_retrieval": expect_retrieval,
        "deterministic_passed": det_passed,
        "deterministic_reason": det_reason,
        "faithfulness_score": round(score, 3),
        "faithfulness_reason": reason,
        "fabricated_citations": fabricated,
        "passed": case_passed,
    }


def run_evaluation(
    dataset_path: str | Path | None = None,
    results_path: str | Path | None = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    threshold: float = DEFAULT_THRESHOLD,
    agent: Any = None,
) -> dict[str, Any]:
    """Run the complete evaluation suite against the dataset."""
    from app.agent import BasicAgent
    from app.db_setup import init_demo_database

    init_demo_database()

    if agent is None:
        agent = BasicAgent()

    cases = load_dataset(dataset_path)
    case_results: list[dict[str, Any]] = []

    print("\n" + "=" * 80)
    print(f"Running Faithfulness Evaluation ({len(cases)} cases) | Judge: {judge_model} | Threshold: {threshold}")
    print("=" * 80)

    for case in cases:
        print(f"Evaluating {case['id']} [{case['category']}]...", end=" ", flush=True)
        res = run_case(agent=agent, case=case, judge_model=judge_model, threshold=threshold)
        status_str = "PASS" if res["passed"] else "FAIL"
        print(f"[{status_str}] (score: {res['faithfulness_score']})")
        case_results.append(res)

    total_cases = len(case_results)
    passed_cases = sum(1 for c in case_results if c["passed"])
    failed_cases = total_cases - passed_cases
    pass_rate = round(passed_cases / total_cases, 3) if total_cases > 0 else 0.0
    mean_faithfulness = (
        round(sum(c["faithfulness_score"] for c in case_results) / total_cases, 3)
        if total_cases > 0
        else 0.0
    )
    fabricated_count = sum(len(c["fabricated_citations"]) for c in case_results)

    summary = {
        "total": total_cases,
        "passed": passed_cases,
        "failed": failed_cases,
        "pass_rate": pass_rate,
        "mean_faithfulness": mean_faithfulness,
        "fabricated_citations_count": fabricated_count,
        "threshold": threshold,
        "judge_model": judge_model,
    }

    full_output = {
        "summary": summary,
        "cases": case_results,
    }

    out_path = Path(results_path or DEFAULT_RESULTS_PATH).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)

    # Print summary table
    print("\n" + "=" * 80)
    print("FAITHFULNESS EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total Cases:                 {total_cases}")
    print(f"Passed:                      {passed_cases}")
    print(f"Failed:                      {failed_cases}")
    print(f"Pass Rate:                   {pass_rate * 100:.1f}%")
    print(f"Mean Faithfulness:           {mean_faithfulness:.3f} (target >= {threshold})")
    print(f"Fabricated Citations:        {fabricated_count} (must be 0)")
    print(f"Results File:                {out_path}")
    print("=" * 80 + "\n")

    return full_output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DeepEval faithfulness evaluation.")
    parser.add_argument("--dataset", type=str, default=str(DEFAULT_DATASET_PATH), help="Path to dataset.json")
    parser.add_argument("--results", type=str, default=str(DEFAULT_RESULTS_PATH), help="Path to write results.json")
    parser.add_argument("--model", type=str, default=DEFAULT_JUDGE_MODEL, help="Judge model name")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Faithfulness threshold (default: 0.8)")
    args = parser.parse_args()

    results = run_evaluation(
        dataset_path=args.dataset,
        results_path=args.results,
        judge_model=args.model,
        threshold=args.threshold,
    )
    summary = results["summary"]
    is_success = (
        summary["failed"] == 0
        and summary["mean_faithfulness"] >= summary["threshold"]
        and summary["fabricated_citations_count"] == 0
    )
    sys.exit(0 if is_success else 1)


if __name__ == "__main__":
    main()
