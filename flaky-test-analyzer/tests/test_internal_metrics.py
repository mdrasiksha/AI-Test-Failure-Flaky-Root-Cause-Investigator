from fastapi.testclient import TestClient

from backend import analytics
from backend.main import app


def test_metrics_auth_and_aggregation(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("ADMIN_METRICS_TOKEN", "independent-test-token")
    # Session a views, uses sample, then completes two own analyses; b only views.
    for event, kind in [("page_view", None), ("sample_used", "sample"), ("analysis_started", "sample"), ("analysis_completed", "sample"), ("analysis_started", "failure"), ("analysis_completed", "failure"), ("analysis_completed", "trace")]:
        analytics.record_event("a", event, kind)
    analytics.record_event("b", "page_view")
    analytics.record_event("b", "analysis_failed", "history", success=False)
    analytics.record_event("a", "ai_analysis_requested", "failure", True)
    analytics.record_event("a", "ai_analysis_completed", "failure", True, True)
    analytics.record_feedback("a", True, analysis_type="failure")
    analytics.record_feedback("b", False, analysis_type="history")

    client = TestClient(app)
    assert client.get("/internal/metrics?days=7").status_code == 401
    assert client.get("/internal/metrics?days=7", headers={"X-Admin-Token": "wrong"}).status_code == 401
    response = client.get("/internal/metrics?days=7", headers={"X-Admin-Token": "independent-test-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["page_views"] == 2
    assert body["analysis_attempts"] == 2
    assert body["successful_analyses"] == 3
    assert body["failed_analyses"] == 1
    assert body["analysis_types"] == {"failure": 1, "history": 0, "sample": 1, "trace": 1}
    assert body["ai_requests"] == body["ai_completed"] == 1
    assert body["anonymous_sessions_with_analysis"] == 1
    assert body["repeat_sessions"] == 1
    assert body["feedback_total"] == 2 and body["helpful_rate"] == 50.0
    assert body["analysis_conversion_rate"] == 50.0
    assert body["sample_to_own_analysis_sessions"] == 1


def test_metrics_disabled_missing_token_days_and_null_rates(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    monkeypatch.delenv("ADMIN_METRICS_TOKEN", raising=False)
    client = TestClient(app)
    assert client.get("/internal/metrics").status_code == 404
    monkeypatch.setenv("ADMIN_METRICS_TOKEN", "token")
    assert client.get("/internal/metrics?days=0", headers={"X-Admin-Token": "token"}).status_code == 422
    body = client.get("/internal/metrics", headers={"X-Admin-Token": "token"}).json()
    assert body["helpful_rate"] is None
    assert body["analysis_conversion_rate"] is None
