import pytest

from backend.playwright_analyzer import analyze_playwright_failure


def failure(message: str | None = None, error_type: str | None = "Error", trace: str | None = None) -> dict[str, object]:
    return {"error_type": error_type, "error_message": message, "stack_trace": trace}


@pytest.mark.parametrize(
    ("message", "issue_type"),
    [
        ("TimeoutError: locator.click: Timeout 5000ms exceeded", "action_timeout"),
        ("locator.click: strict mode violation: resolved to 2 elements", "strict_mode_violation"),
        ("locator.click: element is not visible", "element_not_visible"),
        ("locator.click: element is not enabled", "element_not_enabled"),
        ("locator.click: element was detached from the DOM", "element_detached"),
        ("expect(locator).to_have_text failed: Timeout 5000ms exceeded", "assertion_timeout"),
        ("page.goto: navigation timeout 30000ms exceeded", "navigation_timeout"),
        ("page.goto: net::ERR_CONNECTION_REFUSED", "network_failure"),
        ("browserType.launch: executable doesn't exist", "browser_launch_failure"),
        ("page.click: page has been closed", "page_closed"),
        ("BrowserContext.close: browser context has been closed", "context_closed"),
        ("TargetClosedError: locator.click target closed", "target_closed"),
        ('locator("main div:nth-child(4)").click timed out', "selector_instability"),
        ("APIRequestContext response.status was status 500", "api_response_failure"),
    ],
)
def test_supported_rules(message: str, issue_type: str) -> None:
    result = analyze_playwright_failure(failure(message))
    assert result is not None
    assert result["issue_type"] == issue_type
    assert result["timeout_increase_recommended"] is False
    assert result["evidence"]


def test_generic_assertion_is_not_playwright() -> None:
    assert analyze_playwright_failure(failure("1 != 2", "AssertionError")) is None


def test_generic_timeout_is_not_playwright() -> None:
    assert analyze_playwright_failure(failure("Timeout 5000ms exceeded", "TimeoutError")) is None


def test_missing_error_fields_are_safe() -> None:
    assert analyze_playwright_failure({}) is None


def test_specific_rule_wins_over_action_timeout() -> None:
    result = analyze_playwright_failure(failure("locator.click: Timeout 5000ms exceeded\nelement is not visible"))
    assert result is not None
    assert result["issue_type"] == "element_not_visible"


def test_timeout_and_locator_metadata_extraction() -> None:
    result = analyze_playwright_failure(
        failure(
            'locator.click: Timeout 5000ms exceeded\nCall log:\nwaiting for get_by_role("button", name="Pay")'
        )
    )
    assert result is not None
    assert result["issue_type"] == "locator_not_found"
    assert result["metadata"] == {
        "action": "locator.click",
        "timeout_ms": 5000,
        "locator": 'get_by_role("button", name="Pay")',
    }


def test_unknown_playwright_failure() -> None:
    result = analyze_playwright_failure(failure("Playwright protocol error"))
    assert result is not None
    assert result["issue_type"] == "unknown_playwright_failure"
