import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from backend.ai_analyzer import AIConfigurationError
from backend.main import app

client = TestClient(app)

ANALYSIS = {
    "summary": "The UI was not ready for the click.",
    "root_cause_category": "synchronization",
    "root_cause_confidence": "medium",
    "ownership_hint": "uncertain",
    "evidence": ["locator.click timed out"],
    "hypotheses": [
        {
            "hypothesis": "The screen had not reached its ready state.",
            "confidence": "medium",
        }
    ],
    "recommended_investigation": ["Inspect the trace."],
    "suggested_remediation": ["Wait for a meaningful state."],
    "suggested_code": None,
    "needs_more_evidence": True,
    "additional_evidence_requested": ["Trace"],
}


def post_xml(xml: str):
    return client.post(
        "/analyze-ai", files={"file": ("report.xml", xml, "application/xml")}
    )


def test_passing_test_causes_no_ai_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.main.analyze_with_ai",
        lambda evidence: pytest.fail("AI should not be called"),
    )
    body = post_xml('<testsuite><testcase name="passes"/></testsuite>').json()
    assert body == {"total_tests": 1, "failures_analyzed": 0, "tests": []}


def test_multiple_failures_are_analyzed_and_deterministic_results_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_ANALYSIS_ENABLED", "true")
    evidence_seen = []
    monkeypatch.setattr(
        "backend.main.analyze_with_ai",
        lambda evidence: evidence_seen.append(evidence) or ANALYSIS,
    )
    xml = """<testsuite>
      <testcase classname="ui" name="pay"><failure type="TimeoutError" message="locator.click timed out">Playwright: element is not visible</failure></testcase>
      <testcase classname="api" name="total"><failure type="AssertionError" message="expected 2 received 3">assert mismatch</failure></testcase>
      <testcase name="ok"/>
    </testsuite>"""
    response = post_xml(xml)
    assert response.status_code == 200
    body = response.json()
    assert body["total_tests"] == 3 and body["failures_analyzed"] == 2
    assert len(evidence_seen) == 2
    assert body["tests"][0]["classification"]["category"] == "locator"
    assert body["tests"][0]["framework_analysis"]["framework"] == "playwright"
    assert body["tests"][1]["classification"]["category"] == "assertion"
    assert body["tests"][1]["framework_analysis"] is None
    assert "proof" in body["tests"][0]["ownership_note"]


def test_missing_key_returns_controlled_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_ANALYSIS_ENABLED", "true")
    def missing(evidence: object) -> None:
        raise AIConfigurationError("AI analysis is not configured; set OPENAI_API_KEY")

    monkeypatch.setattr("backend.main.analyze_with_ai", missing)
    response = post_xml(
        '<testsuite><testcase name="bad"><failure>failure</failure></testcase></testsuite>'
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ai_not_configured"


def test_ai_is_disabled_by_default_and_forged_request_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_ANALYSIS_ENABLED", raising=False)
    monkeypatch.setattr(
        "backend.main.analyze_with_ai",
        lambda evidence: pytest.fail("AI should not be called while disabled"),
    )
    response = post_xml(
        '<testsuite><testcase name="bad"><failure type="AssertionError">failure</failure></testcase></testsuite>'
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tests"][0]["classification"]["category"] == "assertion"
    assert body["tests"][0]["ai_analysis"] is None
