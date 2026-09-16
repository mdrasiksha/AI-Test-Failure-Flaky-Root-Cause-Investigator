import pytest

from backend.trace_analyzer import analyze_trace, compact_trace_summary


def trace(error="Timeout exceeded", api="locator.click", selector="#pay", network=None, page_errors=None):
    return {"actions":[{"index":1,"api_name":"page.goto","error":None},{"index":2,"api_name":api,"selector":selector,"error":error,"start_time":9000,"end_time":10000}], "network":network or [], "page_errors":page_errors or []}


@pytest.mark.parametrize("error,api,expected", [
    ("Timeout exceeded", "locator.click", "locator_timeout"),
    ("strict mode violation: 2 elements", "locator.click", "strict_mode_violation"),
    ("Navigation timeout exceeded", "page.goto", "navigation_timeout"),
    ("element is not visible", "locator.click", "element_not_visible"),
    ("Target page has been closed", "locator.click", "browser_or_page_closed"),
])
def test_failure_signals(error, api, expected):
    analysis = analyze_trace(trace(error, api))
    assert analysis["failed_action"]["api_name"] == api
    assert expected in [x["type"] for x in analysis["signals"]]
    assert analysis["recent_actions"][-1]["result"] == "failed"


@pytest.mark.parametrize("network_item,expected", [
    ({"method":"GET","url":"https://example.test/500","status":500}, "http_5xx_before_failure"),
    ({"method":"GET","url":"https://example.test/404","status":404}, "http_4xx_before_failure"),
    ({"method":"GET","url":"https://example.test/x","error":"connection reset"}, "failed_network_request"),
    ({"method":"GET","url":"https://example.test/x","status":200,"duration_ms":5001}, "slow_request_before_failure"),
])
def test_network_signals(network_item, expected):
    result = analyze_trace(trace(network=[network_item]))
    assert result["network_problems"][0]["problem"]
    assert expected in [x["type"] for x in result["signals"]]


def test_page_error_and_compact_summary():
    result = analyze_trace(trace(page_errors=[{"message":"ReferenceError","time":1}]))
    assert "page_error_before_failure" in [x["type"] for x in result["signals"]]
    summary = compact_trace_summary(result)
    assert summary["failed_action"] == "locator.click #pay"
    assert "page.goto" in summary["recent_actions"][0]


def test_no_failure_is_not_guessed_and_timeline_is_limited():
    value = {"actions":[{"index":x,"api_name":"page.click","error":None} for x in range(20)], "network":[], "page_errors":[]}
    result = analyze_trace(value, timeline_limit=3)
    assert result["failed_action"] is None and len(result["recent_actions"]) == 3
