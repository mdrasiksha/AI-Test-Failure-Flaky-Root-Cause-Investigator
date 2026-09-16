"""Deterministic rules for classifying failed JUnit test results.

Rules are evaluated in this explicit priority order so overlapping messages have
predictable results: environment, network, locator, synchronization, test_data,
application, assertion, then unknown.
"""

from __future__ import annotations

from typing import Mapping, TypedDict


class Classification(TypedDict):
    category: str
    confidence: str
    matched_rule: str | None
    explanation: str


class Rule(TypedDict):
    pattern: str
    confidence: str
    explanation: str


def _rules(patterns: list[tuple[str, str]], explanation: str) -> tuple[Rule, ...]:
    return tuple(
        {"pattern": pattern, "confidence": confidence, "explanation": explanation}
        for pattern, confidence in patterns
    )


# Tuple order is the public classification priority, not an incidental detail.
CLASSIFICATION_RULES: tuple[tuple[str, tuple[Rule, ...]], ...] = (
    (
        "environment",
        _rules(
            [
                ("browser not found", "high"),
                ("executable doesn't exist", "high"),
                ("executable not found", "high"),
                ("permission denied", "high"),
                ("config missing", "high"),
                ("certificate", "high"),
                ("ssl", "high"),
                ("proxy", "high"),
                ("browser launch", "high"),
                ("dependency missing", "high"),
                ("environment", "medium"),
                ("configuration", "medium"),
            ],
            "The failure indicates an environment or configuration problem.",
        ),
    ),
    (
        "network",
        _rules(
            [
                ("err_connection_refused", "high"),
                ("err_connection_reset", "high"),
                ("err_name_not_resolved", "high"),
                ("econnrefused", "high"),
                ("connection refused", "high"),
                ("connection reset", "high"),
                ("dns", "high"),
                ("network error", "medium"),
                ("request failed", "medium"),
                ("socket", "medium"),
            ],
            "The test encountered a network connection failure.",
        ),
    ),
    (
        "locator",
        _rules(
            [
                ("strict mode violation", "high"),
                ("no element found", "high"),
                ("element not found", "high"),
                ("unable to locate", "high"),
                ("resolved to multiple elements", "high"),
                ("multiple elements", "high"),
                ("locator", "medium"),
                ("selector", "medium"),
            ],
            "The failure indicates that a UI element locator did not resolve as expected.",
        ),
    ),
    (
        "synchronization",
        _rules(
            [
                ("timeouterror", "high"),
                ("timed out", "high"),
                ("element is not attached", "high"),
                ("stale element", "high"),
                ("timeout", "medium"),
                ("waitfor", "medium"),
                ("wait_for", "medium"),
                ("waiting for", "medium"),
                ("not visible", "medium"),
                ("not enabled", "medium"),
                ("not ready", "medium"),
            ],
            "The failure contains a timing or synchronization-related pattern.",
        ),
    ),
    (
        "test_data",
        _rules(
            [
                ("unique constraint", "high"),
                ("constraint violation", "high"),
                ("duplicate", "high"),
                ("already exists", "high"),
                ("test data", "medium"),
                ("invalid data", "medium"),
                ("missing data", "medium"),
            ],
            "The failure indicates invalid, missing, or conflicting test data.",
        ),
    ),
    (
        "application",
        _rules(
            [
                ("internal server error", "high"),
                ("bad gateway", "high"),
                ("service unavailable", "high"),
                ("server error", "high"),
                ("500", "high"),
                ("502", "high"),
                ("503", "high"),
                ("504", "high"),
            ],
            "The failure indicates a server-side application error.",
        ),
    ),
    (
        "assertion",
        _rules(
            [
                ("assertionerror", "high"),
                ("mismatch", "high"),
                ("to equal", "medium"),
                ("expected", "medium"),
                ("received", "medium"),
                ("assert", "medium"),
                ("to be", "medium"),
            ],
            "The test failed because an assertion did not match the expected result.",
        ),
    ),
)


def classify_failure(test_result: Mapping[str, object]) -> Classification:
    """Classify a failure from its type, message, and trace."""

    searchable = " ".join(
        str(test_result.get(field) or "")
        for field in ("error_type", "error_message", "stack_trace")
    ).lower()
    for category, rules in CLASSIFICATION_RULES:
        for rule in rules:
            if rule["pattern"] in searchable:
                return {
                    "category": category,
                    "confidence": rule["confidence"],
                    "matched_rule": rule["pattern"],
                    "explanation": rule["explanation"],
                }

    return {
        "category": "unknown",
        "confidence": "low",
        "matched_rule": None,
        "explanation": "No known failure pattern was detected.",
    }
