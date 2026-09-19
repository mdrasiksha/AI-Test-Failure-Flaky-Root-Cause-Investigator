import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from backend.main import app
from sample_data.traces.generate_samples import create_sample_archive

client = TestClient(app)


def post(trace_content, use_ai=False, junit=None):
    files = {"trace_file": ("trace.zip", trace_content, "application/zip")}
    if junit: files["junit_file"] = ("report.xml", junit, "application/xml")
    return client.post(f"/analyze-trace?use_ai={str(use_ai).lower()}", files=files)


@pytest.fixture
def trace_content(tmp_path):
    path = create_sample_archive("locator_timeout.zip", tmp_path / "trace.zip")
    return path.read_bytes()


def test_trace_analysis_works_without_ai(monkeypatch, trace_content):
    monkeypatch.setattr("backend.main.analyze_with_ai", lambda evidence: pytest.fail("AI called"))
    response = post(trace_content); assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["failed_action"]["api_name"] == "locator.click"
    assert body["ai_analysis"] is None


def test_ai_receives_only_compact_sanitized_evidence(monkeypatch, trace_content):
    monkeypatch.setenv("AI_ANALYSIS_ENABLED", "true")
    seen = []
    monkeypatch.setattr("backend.main.analyze_with_ai", lambda evidence: seen.append(evidence) or {"summary":"ok"})
    response = post(trace_content, True); assert response.status_code == 200
    evidence = seen[0]
    assert set(evidence["trace_analysis"]) == {"failed_action","failure","recent_actions","network_problems","page_errors","signals"}
    dumped = json.dumps(evidence)
    assert "resources" not in dumped and "trace.zip" not in dumped


def test_trace_and_junit_are_combined_without_claiming_mapping(monkeypatch, trace_content):
    junit = '<testsuite><testcase name="pay"><failure message="timeout">locator.click timeout</failure></testcase></testsuite>'
    body = post(trace_content, junit=junit).json()
    assert body["junit_analysis"][0]["classification"]
    assert "uncertain" in body["mapping_note"]
