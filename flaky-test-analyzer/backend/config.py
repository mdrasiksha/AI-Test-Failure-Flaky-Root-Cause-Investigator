"""Central, environment-backed application configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _positive_int(name: str, default: int, minimum: int = 1) -> int:
    """Read a positive integer while keeping invalid deployments startable."""

    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


APP_ENV = os.getenv("APP_ENV", "development")
PORT = _positive_int("PORT", 8000)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
MAX_UPLOAD_MB = _positive_int("MAX_UPLOAD_MB", 10)
MAX_TRACE_UPLOAD_MB = _positive_int("MAX_TRACE_UPLOAD_MB", 50)
MAX_AI_TESTS_PER_REQUEST = _positive_int("MAX_AI_TESTS_PER_REQUEST", 5)
MAX_HISTORY_FILES = 20
MAX_HISTORY_TOTAL_MB = 50

# Existing trace and sanitization safety bounds remain deliberately conservative.
DEFAULT_MAX_AI_TEXT_CHARS = 12_000
MAX_TRACE_FILES = 2_000
MAX_TRACE_UNCOMPRESSED_MB = 250
MAX_TRACE_ENTRY_MB = 25
MAX_TRACE_COMPRESSION_RATIO = 200
TRACE_TIMELINE_LIMIT = 10
SLOW_REQUEST_THRESHOLD_MS = 5_000


def database_url() -> str | None:
    """Return the optional database URL without logging or exposing it."""

    return os.getenv("DATABASE_URL") or None


def analytics_database_backend() -> str:
    """Select Postgres only for an explicitly configured Postgres URL."""

    url = database_url()
    return "postgresql" if url and url.lower().startswith(("postgres://", "postgresql://")) else "sqlite"


def openai_model() -> str:
    """Return the configured model (read at call time to support test overrides)."""

    return os.getenv("OPENAI_MODEL", OPENAI_MODEL)


def ai_analysis_enabled() -> bool:
    """Return whether optional AI analysis is explicitly enabled."""

    return os.getenv("AI_ANALYSIS_ENABLED", "false").strip().lower() == "true"


def openai_api_key() -> str | None:
    """Return the optional provider key without exposing it through the API."""

    return os.getenv("OPENAI_API_KEY")


def max_ai_text_chars() -> int:
    """Return the text limit, falling back safely when configuration is invalid."""

    return _positive_int("AI_MAX_TEXT_CHARS", DEFAULT_MAX_AI_TEXT_CHARS, 500)


def max_ai_tests_per_request() -> int:
    """Return the maximum number of failed tests sent to the AI provider."""

    return _positive_int("MAX_AI_TESTS_PER_REQUEST", MAX_AI_TESTS_PER_REQUEST)
