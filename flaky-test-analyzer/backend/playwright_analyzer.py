"""Deterministic Playwright-specific failure analysis.

Rules intentionally run in the documented ``RULE_PRIORITY`` order.  This keeps
specific diagnoses (for example, a strict-mode violation) ahead of generic
timeout diagnoses when one Playwright error contains evidence for both.
"""

from __future__ import annotations

import re
from typing import Mapping, NotRequired, TypedDict


class PlaywrightMetadata(TypedDict, total=False):
    action: str
    timeout_ms: int
    locator: str
    url: str
    http_status: int
    expected: str
    received: str


class PlaywrightAnalysis(TypedDict):
    framework: str
    issue_type: str
    category: str
    severity: str
    confidence: str
    evidence: list[str]
    likely_cause: str
    recommended_investigation: list[str]
    suggested_remediation: list[str]
    timeout_increase_recommended: bool
    metadata: NotRequired[PlaywrightMetadata]


RULE_PRIORITY = (
    "strict_mode_violation",
    "browser_launch_failure",
    "page_closed",
    "context_closed",
    "target_closed",
    "network_failure",
    "navigation_timeout",
    "locator_not_found",
    "element_detached",
    "element_not_visible",
    "element_not_enabled",
    "element_not_editable",
    "selector_instability",
    "api_response_failure",
    "assertion_timeout",
    "action_timeout",
    "unknown_playwright_failure",
)

_CONTEXT_PATTERNS = (
    "playwright", "locator.", "locator(", "page.", "expect(", "get_by_role",
    "get_by_test_id", "get_by_text", "get_by_label", "wait_for", "waitfor",
    "browsercontext", "browser.new_page", "strict mode violation", "call log:",
    "waiting for locator", "waiting for get_by", "browsertype.launch",
    "apirequestcontext", "targetclosederror",
)
_TIMEOUT_PATTERNS = ("timeouterror", "timeout exceeded", "timed out", "timeout ")
_ACTION_PATTERNS = ("locator.click", "locator.fill", "page.click", "page.fill")
_ASSERTION_PATTERNS = (
    "expect(", "expect.", "to_be_visible", "to_have_text", "to_have_value",
    "to_be_enabled", "to_contain_text",
)
_NAVIGATION_PATTERNS = (
    "page.goto", "navigation timeout", "waiting for navigation", "wait_for_url",
    "wait_for_load_state",
)


def _contains(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _metadata(raw: str) -> PlaywrightMetadata:
    metadata: PlaywrightMetadata = {}
    action = re.search(
        r"\b(locator\.(?:click|fill|wait_for)|page\.(?:goto|click|fill))\b",
        raw,
        re.IGNORECASE,
    )
    timeout = re.search(r"\btimeout\s+(\d+)\s*ms\b", raw, re.IGNORECASE)
    locator = re.search(
        r"(?:waiting for\s+)((?:get_by_[a-z_]+|locator)\([^\r\n]+\))",
        raw,
        re.IGNORECASE,
    )
    url = re.search(r"https?://[^\s\]\[<>\"']+", raw)
    status = re.search(r"\bstatus(?:\(\))?\s*(?::|=|was|is)?\s*(5\d\d)\b", raw, re.I)
    expected = re.search(
        r"\bexpected(?:\s*:|\s+)(.*?)(?=\s+received(?:\s*:|\s+)|$)",
        raw,
        re.I | re.M,
    )
    received = re.search(r"\breceived(?:\s*:|\s+)(.+)$", raw, re.I | re.M)
    if action:
        metadata["action"] = action.group(1).lower()
    if timeout:
        metadata["timeout_ms"] = int(timeout.group(1))
    if locator:
        metadata["locator"] = locator.group(1).strip()
    if url:
        metadata["url"] = url.group(0).rstrip(".,)")
    if status:
        metadata["http_status"] = int(status.group(1))
    if expected:
        metadata["expected"] = expected.group(1).strip()
    if received:
        metadata["received"] = received.group(1).strip()
    return metadata


def _evidence(raw: str, patterns: tuple[str, ...]) -> list[str]:
    """Return actual, de-duplicated error lines that support the selected rule."""

    evidence: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip()
        lowered = cleaned.lower()
        if cleaned and any(pattern in lowered for pattern in patterns):
            if cleaned not in evidence:
                evidence.append(cleaned)
    return evidence[:5]


_GUIDANCE: dict[str, tuple[str, list[str], list[str]]] = {
    "strict_mode_violation": (
        "The locator matched multiple elements, so Playwright could not select one uniquely.",
        ["Inspect every element matched by the locator.", "Identify a stable attribute that uniquely describes the intended element."],
        ["Use a unique role and accessible name, test id, or another stable unique attribute."],
    ),
    "browser_launch_failure": (
        "Playwright could not launch the configured browser in this environment.",
        ["Verify the browser executable and Playwright browser installation.", "Check runtime dependencies and launch configuration."],
        ["Install the matching Playwright browser and required system dependencies."],
    ),
    "page_closed": ("The page was closed before the operation completed.", ["Trace page creation, teardown, and concurrent cleanup."], ["Keep the page alive until all operations that use it have completed."]),
    "context_closed": ("The browser context was closed before the operation completed.", ["Trace context ownership and fixture teardown order."], ["Close the context only after its pages and pending work are complete."]),
    "target_closed": ("The browser target closed before the operation completed.", ["Inspect browser, page, and context lifecycle events and possible browser crashes."], ["Correct premature teardown or the environment issue that closed the target."]),
    "network_failure": ("The browser encountered a network or name-resolution failure.", ["Verify the target service is reachable from the test environment.", "Inspect the URL, DNS, proxy, and service logs."], ["Restore service connectivity and wait on a meaningful readiness signal before testing."]),
    "navigation_timeout": ("Navigation did not reach the configured completion condition in time.", ["Check application availability and backend/network latency.", "Verify the navigation URL and requested load state."], ["Wait for the application-specific readiness condition rather than adding a fixed sleep."]),
    "locator_not_found": ("The locator did not resolve to an element; it may be incorrect, not rendered, or used on the wrong page state.", ["Verify the locator and current page state.", "Confirm the element exists in the DOM when the action runs."], ["Use a stable locator and wait for the meaningful UI state that renders the element."]),
    "element_detached": ("A DOM re-render or replacement detached the element during the operation.", ["Identify the state change that replaces the element.", "Check whether the test retained an element handle across a re-render."], ["Re-resolve the locator after the expected application state change; do not add arbitrary sleeps."]),
    "element_not_visible": ("The element was located but was not visible, or the application was in an unexpected state.", ["Verify the application reached the expected state.", "Check that the locator identifies the intended element.", "Check loading, overlays, and animations that affect visibility."], ["Wait for the meaningful UI state before interacting.", "Use Playwright locators and assertions that benefit from auto-waiting instead of fixed sleeps."]),
    "element_not_enabled": ("The element was present but was not enabled when Playwright attempted the operation.", ["Determine which application state enables the element.", "Check validation, loading, and permission state."], ["Wait for and assert the state that enables the element before interacting."]),
    "element_not_editable": ("The element was not editable when Playwright attempted to enter data.", ["Verify the locator resolves to the intended input.", "Check readonly, disabled, and application state."], ["Wait for the input's meaningful editable state before filling it."]),
    "selector_instability": ("The failure contains evidence of a potentially brittle selector; it is not proof that the selector caused the failure.", ["Inspect whether DOM structure changes invalidate the selector."], ["Prefer stable Playwright locators such as get_by_role, get_by_test_id, or get_by_label when appropriate."]),
    "api_response_failure": ("A Playwright API request or response assertion reported a server error response.", ["Inspect the response status/body and corresponding server logs.", "Verify request data and environment health."], ["Correct the application or request problem before retrying the assertion."]),
    "assertion_timeout": ("The application state did not satisfy the Playwright expectation before its timeout.", ["Compare the expected and received values.", "Verify the expectation and the application state transition that should satisfy it."], ["Wait on a meaningful state and keep the assertion specific; investigate before increasing its timeout."]),
    "action_timeout": ("A Playwright action did not become actionable before its timeout.", ["Inspect the actionability call log and current UI state.", "Verify the locator points to the intended element."], ["Resolve the underlying actionability condition and rely on Playwright auto-waiting rather than fixed sleeps."]),
    "unknown_playwright_failure": ("The failure is Playwright-related, but no supported specific rule matched.", ["Review the complete Playwright call log and stack trace."], ["Address the first concrete Playwright error in the call log."]),
}


def analyze_playwright_failure(
    test_result: Mapping[str, object],
) -> PlaywrightAnalysis | None:
    """Analyze error fields, returning ``None`` without Playwright evidence."""

    values = [str(test_result.get(field) or "") for field in ("error_type", "error_message", "stack_trace")]
    raw = "\n".join(value for value in values if value)
    text = raw.lower()
    if not raw or not _contains(text, _CONTEXT_PATTERNS):
        return None

    timeout = _contains(text, _TIMEOUT_PATTERNS)
    rules: list[tuple[str, str, tuple[str, ...], bool]] = [
        ("strict_mode_violation", "locator", ("strict mode violation", "resolved to 2 elements", "resolved to multiple elements"), _contains(text, ("strict mode violation", "resolved to 2 elements", "resolved to multiple elements"))),
        ("browser_launch_failure", "environment", ("browsertype.launch", "browser executable", "executable doesn't exist", "failed to launch browser", "browser launch"), _contains(text, ("browsertype.launch", "browser executable", "executable doesn't exist", "failed to launch browser", "browser launch"))),
        ("page_closed", "environment", ("page has been closed", "page closed"), _contains(text, ("page has been closed", "page closed"))),
        ("context_closed", "environment", ("browser context has been closed", "context closed"), _contains(text, ("browser context has been closed", "context closed"))),
        ("target_closed", "environment", ("target closed", "targetclosederror"), _contains(text, ("target closed", "targetclosederror"))),
        ("network_failure", "network", ("net::err_connection_refused", "err_connection_reset", "err_name_not_resolved", "err_timed_out", "request failed", "connection refused"), _contains(text, ("net::err_connection_refused", "err_connection_reset", "err_name_not_resolved", "err_timed_out", "request failed", "connection refused"))),
        ("navigation_timeout", "network", _NAVIGATION_PATTERNS + _TIMEOUT_PATTERNS, timeout and _contains(text, _NAVIGATION_PATTERNS)),
        ("locator_not_found", "locator", ("waiting for locator", "waiting for get_by", "element not found", "no element found", "locator resolved to 0 elements"), _contains(text, ("waiting for locator", "waiting for get_by", "element not found", "no element found", "locator resolved to 0 elements"))),
        ("element_detached", "synchronization", ("element is not attached", "element was detached", "detached from the dom"), _contains(text, ("element is not attached", "element was detached", "detached from the dom"))),
        ("element_not_visible", "synchronization", ("element is not visible", "not visible", "expected locator to be visible", "to_be_visible"), _contains(text, ("element is not visible", "not visible", "expected locator to be visible", "to_be_visible"))),
        ("element_not_enabled", "synchronization", ("element is not enabled", "expected locator to be enabled", "to_be_enabled"), _contains(text, ("element is not enabled", "expected locator to be enabled", "to_be_enabled"))),
        ("element_not_editable", "synchronization", ("element is not editable", "not editable", "to_be_editable"), _contains(text, ("element is not editable", "not editable", "to_be_editable"))),
        ("selector_instability", "locator", ("nth-child", ":nth-child", "xpath=", 'locator("div > div >', "locator('div > div >"), _contains(text, ("nth-child", ":nth-child", "xpath=", 'locator("div > div >', "locator('div > div >")) or bool(re.search(r"xpath\s*=?.{40,}", text))),
        ("api_response_failure", "application", ("apirequestcontext", "response.status", "expect(response", "status 500", "status 502", "status 503", "status 504"), _contains(text, ("apirequestcontext", "response.status", "expect(response")) and bool(re.search(r"\b(?:status\D{0,8})?(?:500|502|503|504)\b", text))),
        ("assertion_timeout", "assertion", _ASSERTION_PATTERNS + _TIMEOUT_PATTERNS, _contains(text, _ASSERTION_PATTERNS) and (timeout or _contains(text, ("failed", "expected", "received")))),
        ("action_timeout", "synchronization", _ACTION_PATTERNS + _TIMEOUT_PATTERNS, timeout and _contains(text, _ACTION_PATTERNS)),
    ]
    selected = next((rule for rule in rules if rule[3]), None)
    if selected:
        issue_type, category, evidence_patterns, _ = selected
    else:
        issue_type, category, evidence_patterns = "unknown_playwright_failure", "unknown", _CONTEXT_PATTERNS

    cause, investigation, remediation = _GUIDANCE[issue_type]
    result: PlaywrightAnalysis = {
        "framework": "playwright",
        "issue_type": issue_type,
        "category": category,
        "severity": "medium" if issue_type in {"selector_instability", "unknown_playwright_failure"} else "high",
        "confidence": "medium" if issue_type in {"selector_instability", "unknown_playwright_failure"} else "high",
        "evidence": _evidence(raw, evidence_patterns),
        "likely_cause": cause,
        "recommended_investigation": investigation,
        "suggested_remediation": remediation,
        "timeout_increase_recommended": False,
    }
    metadata = _metadata(raw)
    if metadata:
        result["metadata"] = metadata
    return result
