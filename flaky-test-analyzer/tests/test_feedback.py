import sqlite3

from fastapi.testclient import TestClient

from backend.main import app


def test_feedback_yes_no_optional_and_html_is_data(tmp_path, monkeypatch):
    db = tmp_path / "analytics.db"
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(db))
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    client = TestClient(app)
    assert client.post("/feedback", json={"useful": True, "analysis_type": "failure"}).status_code == 200
    text = "<script>alert('not executable')</script>"
    assert client.post("/feedback", json={"useful": False, "feedback_text": text, "analysis_type": "trace"}).status_code == 200
    with sqlite3.connect(db) as connection:
        rows = connection.execute("SELECT useful, feedback_text FROM analysis_feedback ORDER BY id").fetchall()
    assert rows == [(1, None), (0, text)]


def test_feedback_validation_and_disabled_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    client = TestClient(app)
    assert client.post("/feedback", json={"useful": "yes"}).status_code == 422
    assert client.post("/feedback", json={"useful": True, "feedback_text": "x" * 501}).status_code == 422
    assert client.post("/feedback", json={"useful": True, "analysis_type": "selenium"}).status_code == 422
    monkeypatch.setenv("ANALYTICS_ENABLED", "false")
    assert client.post("/feedback", json={"useful": True}).status_code == 503


def test_success_report_contains_feedback_and_privacy(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "a.db"))
    client = TestClient(app)
    report = client.get("/sample")
    assert "Was this analysis useful?" in report.text
    assert 'maxlength="500"' in report.text
    assert "Please don't include passwords" in report.text
    privacy = client.get("/privacy")
    assert privacy.status_code == 200
    assert "not intentionally retained" in privacy.text
