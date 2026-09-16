import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from backend.ai_analyzer import (
    AIAnalyzerError,
    AIConfigurationError,
    AIResponseError,
    analyze_with_ai,
)


def valid_analysis(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "summary": "The element was not visible when clicked.",
        "root_cause_category": "synchronization",
        "root_cause_confidence": "medium",
        "ownership_hint": "uncertain",
        "evidence": ["locator.click timed out"],
        "hypotheses": [
            {
                "hypothesis": "The expected UI state was not reached.",
                "confidence": "medium",
            }
        ],
        "recommended_investigation": ["Inspect the failed-run trace."],
        "suggested_remediation": ["Wait for the meaningful ready state."],
        "suggested_code": None,
        "needs_more_evidence": True,
        "additional_evidence_requested": ["Playwright trace"],
    }
    value.update(changes)
    return value


def client_returning(value: object) -> SimpleNamespace:
    def create(**kwargs: object) -> SimpleNamespace:
        output = value if isinstance(value, str) else json.dumps(value)
        return SimpleNamespace(output_text=output)

    return SimpleNamespace(responses=SimpleNamespace(create=create))


def test_valid_structured_response_and_request_shape() -> None:
    calls = []
    client = client_returning(valid_analysis())
    original = client.responses.create
    client.responses.create = lambda **kwargs: (
        calls.append(kwargs),
        original(**kwargs),
    )[1]
    result = analyze_with_ai(
        {"test_name": "pay", "error": {"message": "timeout"}}, client=client
    )
    assert result["root_cause_category"] == "synchronization"
    assert calls[0]["text"]["format"]["strict"] is True


def test_invalid_json_response() -> None:
    with pytest.raises(AIResponseError, match="malformed JSON"):
        analyze_with_ai({}, client=client_returning("not-json"))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("root_cause_category", "database", "category"),
        ("root_cause_confidence", "93%", "confidence"),
        ("ownership_hint", "developer", "ownership"),
    ],
)
def test_rejects_unsupported_enums(field: str, value: str, message: str) -> None:
    with pytest.raises(AIResponseError, match=message):
        analyze_with_ai({}, client=client_returning(valid_analysis(**{field: value})))


def test_missing_api_key_is_controlled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AIConfigurationError, match="not configured"):
        analyze_with_ai({})


def test_provider_timeout_is_controlled() -> None:
    def timeout(**kwargs: object) -> None:
        raise openai.APITimeoutError(
            request=httpx.Request("POST", "https://example.invalid")
        )

    client = SimpleNamespace(responses=SimpleNamespace(create=timeout))
    with pytest.raises(AIAnalyzerError, match="temporarily unavailable"):
        analyze_with_ai({}, client=client)


def test_provider_rate_limit_is_controlled() -> None:
    def limited(**kwargs: object) -> None:
        response = httpx.Response(
            429, request=httpx.Request("POST", "https://example.invalid")
        )
        raise openai.RateLimitError("rate limited", response=response, body=None)

    client = SimpleNamespace(responses=SimpleNamespace(create=limited))
    with pytest.raises(AIAnalyzerError, match="rate limit"):
        analyze_with_ai({}, client=client)
