"""Step 9D database selection and portable persistence coverage."""

from pathlib import Path

from fastapi.testclient import TestClient

from backend import analytics
from backend.main import app


class FakeCursor:
    rowcount = 1

    def fetchall(self):
        return []

    def fetchone(self):
        return (0, 0)

    def __iter__(self):
        return iter(())


class FakePostgresConnection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        return FakeCursor()


def test_database_url_absent_selects_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "analytics.db"))
    assert analytics.database_backend() == "sqlite"
    assert analytics.initialize_storage()
    assert (tmp_path / "analytics.db").is_file()


def test_postgres_url_selects_postgres_and_uses_parameterized_queries(monkeypatch):
    secret = "postgresql://private-user:private-password@internal/db"
    connection = FakePostgresConnection()
    monkeypatch.setenv("DATABASE_URL", secret)
    monkeypatch.setattr(analytics, "_connect", lambda: connection)
    assert analytics.database_backend() == "postgresql"
    assert analytics.initialize_storage()
    assert analytics.record_event("opaque", "page_view")
    assert analytics.record_feedback("opaque", True, analysis_type="failure")
    insert_calls = [(sql, params) for sql, params in connection.calls if sql.lstrip().startswith("INSERT")]
    assert len(insert_calls) == 2
    assert all("%s" in sql and secret not in sql for sql, _ in insert_calls)
    assert all(params and "opaque" in params for _, params in insert_calls)


def test_postgres_schema_remains_privacy_minimal(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://internal/example")
    schema = " ".join(analytics._schema_statements()).lower()
    expected = {
        "id", "created_at", "anonymous_session_id", "event", "analysis_type",
        "ai_enabled", "success", "useful", "feedback_text",
    }
    forbidden = {
        "filename", "test_name", "classname", "stack_trace", "error_message",
        "selector", "trace_url", "source_code", "uploaded_artifact", "ip_address",
        "user_agent", "email", "name", "company",
    }
    assert all(column in schema for column in expected)
    assert not any(column in schema for column in forbidden)


def test_database_url_is_not_exposed_by_health_metrics_or_ui(monkeypatch, tmp_path):
    secret = "postgresql://secret-user:secret-password@private-host/private-db"
    monkeypatch.setenv("DATABASE_URL", secret)
    monkeypatch.setenv("ADMIN_METRICS_TOKEN", "admin-token")
    monkeypatch.setattr(analytics, "aggregate_metrics", lambda days: {"period_days": days})
    monkeypatch.setattr(analytics, "record_event", lambda *args, **kwargs: True)
    client = TestClient(app)
    responses = (
        client.get("/health"), client.get("/"),
        client.get("/internal/metrics", headers={"X-Admin-Token": "admin-token"}),
    )
    assert all(response.status_code == 200 for response in responses)
    assert all(secret not in response.text and "secret-password" not in response.text for response in responses)


def test_example_environment_has_blank_database_url():
    example = Path(__file__).resolve().parents[1] / ".env.example"
    assert "DATABASE_URL=\n" in example.read_text()
