from backend.classifier import classify_failure


def failure(
    error_type: str | None = None, message: str | None = None
) -> dict[str, object]:
    return {"error_type": error_type, "error_message": message, "stack_trace": None}


def test_timeout_error_is_synchronization() -> None:
    result = classify_failure(failure("TimeoutError", "Timeout 5000ms exceeded"))
    assert result["category"] == "synchronization"
    assert result["confidence"] == "high"
    assert result["matched_rule"] == "timeouterror"


def test_strict_mode_violation_is_locator() -> None:
    assert (
        classify_failure(failure(message="strict mode violation"))["category"]
        == "locator"
    )


def test_connection_refused_is_network() -> None:
    assert (
        classify_failure(failure(message="ERR_CONNECTION_REFUSED"))["category"]
        == "network"
    )


def test_internal_server_error_is_application() -> None:
    assert (
        classify_failure(failure(message="HTTP 500 internal server error"))["category"]
        == "application"
    )


def test_assertion_error_is_assertion() -> None:
    assert classify_failure(failure("AssertionError"))["category"] == "assertion"


def test_duplicate_is_test_data() -> None:
    assert (
        classify_failure(failure(message="duplicate test data"))["category"]
        == "test_data"
    )


def test_certificate_proxy_error_is_environment() -> None:
    assert (
        classify_failure(failure(message="certificate rejected by proxy"))["category"]
        == "environment"
    )


def test_unknown_error_is_low_confidence_unknown() -> None:
    result = classify_failure(failure("SomethingOdd", None))
    assert result["category"] == "unknown"
    assert result["confidence"] == "low"
    assert result["matched_rule"] is None


def test_passed_test_has_no_api_classification() -> None:
    import pytest

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from backend.main import app

    response = TestClient(app).post(
        "/upload-junit",
        files={
            "file": (
                "run.xml",
                '<testsuite><testcase name="ok"/></testsuite>',
                "application/xml",
            )
        },
    )
    assert response.status_code == 200
    assert response.json()["tests"][0]["classification"] is None


def test_overlapping_patterns_respect_documented_priority() -> None:
    result = classify_failure(
        failure(message="proxy network error: locator timeout and assertion mismatch")
    )
    assert result["category"] == "environment"
    assert result["matched_rule"] == "proxy"
