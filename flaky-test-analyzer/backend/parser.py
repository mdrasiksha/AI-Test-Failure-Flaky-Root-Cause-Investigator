"""Utilities for turning JUnit XML reports into normalized test results."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TypedDict


class JUnitParseError(ValueError):
    """Raised when a JUnit report cannot be parsed."""


class TestResult(TypedDict):
    """The normalized representation of one JUnit testcase."""

    test_name: str
    classname: str | None
    duration: float | None
    status: str
    error_type: str | None
    error_message: str | None
    stack_trace: str | None


def _local_name(tag: str) -> str:
    """Return an XML tag without an optional namespace."""

    return tag.rsplit("}", 1)[-1]


def _clean_text(element: ET.Element) -> str | None:
    text = "".join(element.itertext()).strip()
    return " ".join(text.split()) or None


def _duration(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise JUnitParseError(f"Invalid testcase duration: {value!r}") from exc


def parse_junit_xml(xml_content: str | bytes) -> list[TestResult]:
    """Parse JUnit XML content and return one dictionary per testcase.

    Both a single ``testsuite`` and a ``testsuites`` container are supported.
    XML namespaces are tolerated. Invalid XML and invalid duration values are
    reported with :class:`JUnitParseError` so callers can present a useful
    client-facing error.
    """

    try:
        root = ET.fromstring(xml_content)
    except (ET.ParseError, TypeError, ValueError) as exc:
        raise JUnitParseError(f"Malformed JUnit XML: {exc}") from exc

    if _local_name(root.tag) not in {"testsuite", "testsuites"}:
        raise JUnitParseError(
            "Invalid JUnit XML: root element must be 'testsuite' or 'testsuites'"
        )

    results: list[TestResult] = []
    for testcase in (item for item in root.iter() if _local_name(item.tag) == "testcase"):
        status = "passed"
        error_type = None
        error_message = None
        stack_trace = None

        outcome = next(
            (
                child
                for child in testcase
                if _local_name(child.tag) in {"failure", "error", "skipped"}
            ),
            None,
        )
        if outcome is not None:
            outcome_name = _local_name(outcome.tag)
            status = {"failure": "failed", "error": "error", "skipped": "skipped"}[
                outcome_name
            ]
            if outcome_name in {"failure", "error"}:
                error_type = outcome.get("type")
                error_message = outcome.get("message")
                stack_trace = _clean_text(outcome)

        results.append(
            {
                "test_name": testcase.get("name", ""),
                "classname": testcase.get("classname"),
                "duration": _duration(testcase.get("time")),
                "status": status,
                "error_type": error_type,
                "error_message": error_message,
                "stack_trace": stack_trace,
            }
        )

    return results
