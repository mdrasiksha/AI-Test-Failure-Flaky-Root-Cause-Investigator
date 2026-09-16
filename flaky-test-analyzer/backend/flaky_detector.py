"""Historical, heuristic flaky-test detection for parsed JUnit runs."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, TypedDict


class FlakyAnalysis(TypedDict):
    test_id: str
    total_runs: int
    executed_runs: int
    passed_runs: int
    failed_runs: int
    error_runs: int
    skipped_runs: int
    failure_rate: float
    status_transitions: int
    flaky_status: str
    explanation: str


def get_test_id(test_result: Mapping[str, object]) -> str:
    """Build the stable test identity ``classname::test_name`` when possible."""

    name = str(test_result.get("test_name") or "")
    classname = test_result.get("classname")
    return f"{classname}::{name}" if classname else name


def _status_and_explanation(
    total: int, executed: int, passed: int, failures: int, transitions: int
) -> tuple[str, str]:
    # A history spanning at least three uploaded appearances is stable when every
    # actual execution passed; skipped appearances do not make it flaky.
    if total >= 3 and executed and passed == executed:
        return "stable", "This test passed in every executed run."
    if executed < 3:
        return (
            "insufficient_history",
            "At least three executed runs are needed to assess flakiness.",
        )
    if failures == executed:
        return (
            "consistently_failing",
            "This test failed or errored in every executed run.",
        )
    if passed and failures and transitions:
        if executed >= 5 and transitions >= 2:
            return (
                "high",
                "This test alternated between passing and failing across multiple executions.",
            )
        return (
            "possible",
            "This test has both passing and failing results in its execution history.",
        )
    return "possible", "This test has inconsistent execution results."


def analyze_history(
    runs: Iterable[Iterable[Mapping[str, object]]],
) -> list[FlakyAnalysis]:
    """Aggregate tests across chronologically ordered runs and apply the heuristic."""

    histories: dict[str, list[str]] = defaultdict(list)
    for run in runs:
        for test in run:
            histories[get_test_id(test)].append(str(test.get("status") or "").lower())

    analyses: list[FlakyAnalysis] = []
    for test_id, statuses in histories.items():
        passed = statuses.count("passed")
        failed = statuses.count("failed")
        errors = statuses.count("error")
        skipped = statuses.count("skipped")
        executed_statuses = [
            status for status in statuses if status in {"passed", "failed", "error"}
        ]
        # A failed result changing to an error (or vice versa) is still continuously
        # non-passing. Collapse both outcomes for meaningful pass/failure transitions.
        transition_statuses = [
            "passed" if status == "passed" else "failure"
            for status in executed_statuses
        ]
        transitions = sum(
            current != previous
            for previous, current in zip(transition_statuses, transition_statuses[1:])
        )
        executed = passed + failed + errors
        failures = failed + errors
        flaky_status, explanation = _status_and_explanation(
            len(statuses), executed, passed, failures, transitions
        )
        analyses.append(
            {
                "test_id": test_id,
                "total_runs": len(statuses),
                "executed_runs": executed,
                "passed_runs": passed,
                "failed_runs": failed,
                "error_runs": errors,
                "skipped_runs": skipped,
                "failure_rate": (
                    round(failures / executed * 100, 2) if executed else 0.0
                ),
                "status_transitions": transitions,
                "flaky_status": flaky_status,
                "explanation": explanation,
            }
        )
    return analyses
