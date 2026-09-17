"""Integration coverage for the small server-rendered product interface."""
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

import backend.main as main

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(main.app)


def test_home_is_product_html_and_forms_exist():
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    for text in ("Find out why your automated test failed.", "Test Failure", "Flaky History", "Playwright Trace", "Try Sample"):
        assert text in response.text


def test_health_and_original_api_remain_available():
    assert client.get("/health").json() == {
        "status": "ok", "service": "flaky-test-analyzer"
    }
    sample = (ROOT / "sample_data/junit.xml").read_bytes()
    assert client.post("/upload-junit", files={"file": ("run.xml", sample, "application/xml")}).status_code == 200


def test_valid_junit_produces_report():
    sample = (ROOT / "sample_data/playwright/locator_timeout.xml").read_bytes()
    response = client.post("/ui/analyze-junit", files={"file": ("run.xml", sample, "application/xml")})
    assert response.status_code == 200
    assert "Test Failure Analysis" in response.text
    assert "Playwright Analysis" in response.text
    assert "Locator Not Found" in response.text


def test_invalid_junit_is_a_controlled_error():
    response = client.post("/ui/analyze-junit", files={"file": ("bad.xml", b"<broken", "application/xml")})
    assert response.status_code == 400
    assert "couldn’t analyze" in response.text
    assert "Traceback" not in response.text


def test_history_produces_report():
    files = [("files", (path.name, path.read_bytes(), "application/xml")) for path in sorted((ROOT / "sample_data/history").glob("*.xml"))]
    response = client.post("/ui/analyze-history", files=files)
    assert response.status_code == 200
    assert "Flaky History Analysis" in response.text
    assert "Transitions:" in response.text
    assert "HIGH" in response.text


def test_trace_produces_report():
    subprocess.run(["python", "sample_data/traces/generate_samples.py"], cwd=ROOT, check=True)
    archive = (ROOT / "sample_data/traces/locator_timeout.zip").read_bytes()
    response = client.post("/ui/analyze-trace", files={"trace_file": ("trace.zip", archive, "application/zip")})
    assert response.status_code == 200
    assert "Actions Before Failure" in response.text
    assert "locator.click" in response.text


def _ai_result():
    return {"summary": "The locator may be stale.", "root_cause_category": "locator", "root_cause_confidence": "high", "ownership_hint": "test", "evidence": ["locator timed out"], "hypotheses": [{"hypothesis": "UI changed", "confidence": "medium"}], "recommended_investigation": ["Inspect locator"], "suggested_remediation": ["Use a role locator"], "suggested_code": "page.get_by_role('button').click()", "needs_more_evidence": False, "additional_evidence_requested": []}


def test_ai_checkbox_uses_mocked_ai(monkeypatch):
    monkeypatch.setattr(main, "analyze_with_ai", lambda evidence: _ai_result())
    sample = (ROOT / "sample_data/playwright/locator_timeout.xml").read_bytes()
    response = client.post("/ui/analyze-junit", data={"use_ai": "true"}, files={"file": ("run.xml", sample, "application/xml")})
    assert response.status_code == 200
    assert "AI Investigation" in response.text
    assert "Suggested code" in response.text


def test_missing_ai_key_is_friendly(monkeypatch):
    def unavailable(evidence):
        raise main.AIConfigurationError("OPENAI_API_KEY is not configured")
    monkeypatch.setattr(main, "analyze_with_ai", unavailable)
    sample = (ROOT / "sample_data/playwright/locator_timeout.xml").read_bytes()
    response = client.post("/ui/analyze-junit", data={"use_ai": "true"}, files={"file": ("run.xml", sample, "application/xml")})
    assert response.status_code == 503
    assert "AI analysis is not configured. You can continue using deterministic analysis." in response.text


def test_sample_demo_works():
    response = client.get("/sample")
    assert response.status_code == 200
    assert "Sample: Playwright Locator Timeout" in response.text
    assert "Locator Not Found" in response.text


def test_uploaded_html_and_raw_json_are_escaped():
    xml = b'''<testsuite><testcase name="&lt;script&gt;alert(1)&lt;/script&gt;"><failure type="AssertionError" message="&lt;img src=x onerror=alert(1)&gt;">bad</failure></testcase></testsuite>'''
    response = client.post("/ui/analyze-junit", files={"file": ("x.xml", xml, "application/xml")})
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "<img src=x onerror=alert(1)>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "\\u003cscript\\u003e" in response.text
