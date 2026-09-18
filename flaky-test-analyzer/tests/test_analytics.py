import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from backend import analytics
from backend.main import app


def _events(path):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT event, analysis_type, ai_enabled, success FROM analytics_events ORDER BY id"
        ).fetchall()


def test_storage_page_sample_and_safe_schema(tmp_path, monkeypatch):
    db = tmp_path / "nested" / "analytics.db"
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(db))
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    assert analytics.initialize_storage()
    client = TestClient(app)
    assert client.get("/?ignored=secret").status_code == 200
    assert client.get("/sample").status_code == 200
    rows = _events(db)
    assert ("page_view", None, None, None) in rows
    assert ("sample_used", "sample", None, None) in rows
    assert ("analysis_started", "sample", None, None) in rows
    assert ("analysis_completed", "sample", None, 1) in rows
    with sqlite3.connect(db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(analytics_events)")}
    assert columns == {"id", "created_at", "anonymous_session_id", "event", "analysis_type", "ai_enabled", "success"}
    assert not columns.intersection({"filename", "test_name", "stack_trace", "selector", "url", "ip"})


def test_random_session_cookie_flags_and_not_ip(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("APP_ENV", "development")
    response = TestClient(app).get("/", headers={"X-Forwarded-For": "203.0.113.7"})
    cookie = response.headers["set-cookie"]
    assert "anonymous_session_id=" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie and "203.0.113.7" not in cookie

    monkeypatch.setenv("APP_ENV", "production")
    production = TestClient(app).get("/")
    assert "Secure" in production.headers["set-cookie"]


def test_cleanup_and_disabled_mode(tmp_path, monkeypatch):
    db = tmp_path / "a.db"
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(db))
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    analytics.initialize_storage()
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO analytics_events (created_at, anonymous_session_id, event) VALUES (?, ?, ?)",
            (old, "opaque", "page_view"),
        )
    assert analytics.cleanup_expired_events(30) == 1
    monkeypatch.setenv("ANALYTICS_ENABLED", "false")
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "disabled.db"))
    assert TestClient(app).get("/health").status_code == 200
    assert not (tmp_path / "disabled.db").exists()


def test_analytics_exception_does_not_break_analysis(monkeypatch):
    monkeypatch.setattr(analytics, "record_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert TestClient(app).get("/sample").status_code == 200
