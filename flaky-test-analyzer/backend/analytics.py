"""Privacy-first, aggregate-only product validation analytics."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.config import analytics_database_backend, database_url

logger = logging.getLogger(__name__)

ALLOWED_EVENTS = frozenset(
    {
        "page_view", "sample_used", "analysis_started", "analysis_completed",
        "analysis_failed", "ai_analysis_requested", "ai_analysis_completed",
    }
)
ALLOWED_ANALYSIS_TYPES = frozenset({"failure", "history", "trace", "sample"})


class AnalyticsStorageError(RuntimeError):
    """Indicate that aggregate analytics storage is unavailable."""


def analytics_enabled() -> bool:
    return os.getenv("ANALYTICS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def database_path() -> Path:
    return Path(os.getenv("ANALYTICS_DB_PATH", "data/analytics.db"))


def database_backend() -> str:
    """Expose the selected backend name, never its credentials."""

    return analytics_database_backend()


def _connect() -> AbstractContextManager[Any]:
    if database_backend() == "postgresql":
        import psycopg

        # The URL is passed directly to the driver and is deliberately never logged.
        return psycopg.connect(database_url(), connect_timeout=5)
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path, timeout=5)


def _sql(statement: str) -> str:
    """Translate our single portable placeholder style for the selected driver."""

    return statement.replace("?", "%s") if database_backend() == "postgresql" else statement


def _schema_statements() -> tuple[str, ...]:
    if database_backend() == "postgresql":
        return (
            """CREATE TABLE IF NOT EXISTS analytics_events (
                id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL,
                anonymous_session_id TEXT NOT NULL, event TEXT NOT NULL,
                analysis_type TEXT, ai_enabled BOOLEAN, success BOOLEAN)""",
            "CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at ON analytics_events(created_at)",
            """CREATE TABLE IF NOT EXISTS analysis_feedback (
                id BIGSERIAL PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL,
                anonymous_session_id TEXT NOT NULL, useful BOOLEAN NOT NULL,
                feedback_text TEXT, analysis_type TEXT)""",
            "CREATE INDEX IF NOT EXISTS idx_analysis_feedback_created_at ON analysis_feedback(created_at)",
        )
    return (
        """CREATE TABLE IF NOT EXISTS analytics_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            anonymous_session_id TEXT NOT NULL, event TEXT NOT NULL,
            analysis_type TEXT, ai_enabled INTEGER, success INTEGER)""",
        "CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at ON analytics_events(created_at)",
        """CREATE TABLE IF NOT EXISTS analysis_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            anonymous_session_id TEXT NOT NULL, useful INTEGER NOT NULL,
            feedback_text TEXT, analysis_type TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_analysis_feedback_created_at ON analysis_feedback(created_at)",
    )


def initialize_storage() -> bool:
    """Idempotently create the intentionally minimal schema when enabled."""
    if not analytics_enabled():
        return False
    try:
        with _connect() as connection:
            for statement in _schema_statements():
                connection.execute(statement)
        return True
    except Exception:
        logger.warning("Product analytics storage could not be initialized")
        return False


def _boolean(value: bool | None) -> bool | int | None:
    if value is None or database_backend() == "postgresql":
        return value
    return int(value)


def record_event(
    anonymous_session_id: str, event: str, analysis_type: str | None = None,
    ai_enabled: bool | None = None, success: bool | None = None,
) -> bool:
    """Record only allow-listed product metadata; never accept diagnostics."""
    if not analytics_enabled():
        return False
    if event not in ALLOWED_EVENTS or (analysis_type is not None and analysis_type not in ALLOWED_ANALYSIS_TYPES):
        logger.warning("Rejected invalid product analytics metadata")
        return False
    try:
        if not initialize_storage():
            return False
        with _connect() as connection:
            connection.execute(
                _sql("""INSERT INTO analytics_events
                    (created_at, anonymous_session_id, event, analysis_type, ai_enabled, success)
                    VALUES (?, ?, ?, ?, ?, ?)"""),
                (datetime.now(UTC).isoformat(), anonymous_session_id, event, analysis_type,
                 _boolean(ai_enabled), _boolean(success)),
            )
        return True
    except Exception:
        logger.warning("Product analytics event could not be recorded")
        return False


def record_feedback(
    anonymous_session_id: str, useful: bool, feedback_text: str | None = None,
    analysis_type: str | None = None,
) -> bool:
    if not analytics_enabled():
        return False
    if analysis_type is not None and analysis_type not in ALLOWED_ANALYSIS_TYPES:
        return False
    try:
        if not initialize_storage():
            return False
        with _connect() as connection:
            connection.execute(
                _sql("""INSERT INTO analysis_feedback
                    (created_at, anonymous_session_id, useful, feedback_text, analysis_type)
                    VALUES (?, ?, ?, ?, ?)"""),
                (datetime.now(UTC).isoformat(), anonymous_session_id, _boolean(useful), feedback_text, analysis_type),
            )
        return True
    except Exception:
        logger.warning("Product feedback could not be recorded")
        return False


def cleanup_expired_events(retention_days: int | None = None) -> int:
    """Remove analytics and feedback older than the configured retention window."""
    if not analytics_enabled():
        return 0
    try:
        days = retention_days or max(1, int(os.getenv("ANALYTICS_RETENTION_DAYS", "30")))
    except ValueError:
        days = 30
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    try:
        if not initialize_storage():
            return 0
        with _connect() as connection:
            events = connection.execute(_sql("DELETE FROM analytics_events WHERE created_at < ?"), (cutoff,)).rowcount
            feedback = connection.execute(_sql("DELETE FROM analysis_feedback WHERE created_at < ?"), (cutoff,)).rowcount
        return events + feedback
    except Exception:
        logger.warning("Expired product analytics could not be cleaned up")
        return 0


def aggregate_metrics(days: int) -> dict[str, object]:
    """Return aggregates only; no session IDs or feedback text leave this module."""
    if not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    try:
        if not initialize_storage():
            raise AnalyticsStorageError("analytics storage is unavailable")
        with _connect() as connection:
            counts = dict(connection.execute(_sql(
                "SELECT event, COUNT(*) FROM analytics_events WHERE created_at >= ? GROUP BY event"
            ), (cutoff,)).fetchall())
            type_counts = {name: 0 for name in sorted(ALLOWED_ANALYSIS_TYPES)}
            for analysis_type, total in connection.execute(_sql(
                """SELECT analysis_type, COUNT(*) FROM analytics_events
                   WHERE created_at >= ? AND event = ? GROUP BY analysis_type"""
            ), (cutoff, "analysis_completed")):
                if analysis_type in type_counts:
                    type_counts[analysis_type] = total
            completed_sessions = connection.execute(_sql(
                "SELECT COUNT(DISTINCT anonymous_session_id) FROM analytics_events WHERE created_at >= ? AND event = ?"
            ), (cutoff, "analysis_completed")).fetchone()[0]
            repeat_sessions = connection.execute(_sql(
                """SELECT COUNT(*) FROM (SELECT anonymous_session_id FROM analytics_events
                   WHERE created_at >= ? AND event = ? GROUP BY anonymous_session_id HAVING COUNT(*) > 1) repeated"""
            ), (cutoff, "analysis_completed")).fetchone()[0]
            page_sessions = connection.execute(_sql(
                "SELECT COUNT(DISTINCT anonymous_session_id) FROM analytics_events WHERE created_at >= ? AND event = ?"
            ), (cutoff, "page_view")).fetchone()[0]
            sample_to_own = connection.execute(_sql(
                """SELECT COUNT(DISTINCT sample.anonymous_session_id) FROM analytics_events sample
                   WHERE sample.created_at >= ? AND sample.event = ?
                   AND EXISTS (SELECT 1 FROM analytics_events own
                     WHERE own.anonymous_session_id = sample.anonymous_session_id
                     AND own.event = ? AND own.analysis_type != ? AND own.created_at > sample.created_at)"""
            ), (cutoff, "sample_used", "analysis_completed", "sample")).fetchone()[0]
            yes, no = connection.execute(_sql(
                """SELECT COALESCE(SUM(CASE WHEN useful = ? THEN 1 ELSE 0 END), 0),
                          COALESCE(SUM(CASE WHEN useful = ? THEN 1 ELSE 0 END), 0)
                   FROM analysis_feedback WHERE created_at >= ?"""
            ), (_boolean(True), _boolean(False), cutoff)).fetchone()
    except AnalyticsStorageError:
        raise
    except Exception as error:
        logger.warning("Product analytics metrics could not be aggregated")
        raise AnalyticsStorageError("analytics storage is unavailable") from error
    total = yes + no
    return {
        "period_days": days, "page_views": counts.get("page_view", 0),
        "analysis_attempts": counts.get("analysis_started", 0),
        "successful_analyses": counts.get("analysis_completed", 0),
        "failed_analyses": counts.get("analysis_failed", 0), "sample_uses": counts.get("sample_used", 0),
        "analysis_types": type_counts, "ai_requests": counts.get("ai_analysis_requested", 0),
        "ai_completed": counts.get("ai_analysis_completed", 0),
        "anonymous_sessions_with_analysis": completed_sessions, "repeat_sessions": repeat_sessions,
        "feedback_yes": yes, "feedback_no": no, "feedback_total": total,
        "helpful_rate": round(yes / total * 100, 2) if total else None,
        "analysis_conversion_rate": round(completed_sessions / page_sessions * 100, 2) if page_sessions else None,
        "sample_to_own_analysis_sessions": sample_to_own,
    }
