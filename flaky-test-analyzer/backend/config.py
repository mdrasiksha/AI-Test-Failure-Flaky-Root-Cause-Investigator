"""Central configuration for the optional AI investigator."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_MAX_AI_TEXT_CHARS = 12_000
MAX_TRACE_UPLOAD_MB = 50
MAX_TRACE_FILES = 2_000
MAX_TRACE_UNCOMPRESSED_MB = 250
MAX_TRACE_ENTRY_MB = 25
MAX_TRACE_COMPRESSION_RATIO = 200
TRACE_TIMELINE_LIMIT = 10
SLOW_REQUEST_THRESHOLD_MS = 5_000


def openai_model() -> str:
    """Return the configured model without duplicating its default elsewhere."""

    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def max_ai_text_chars() -> int:
    """Return the text limit, falling back safely when configuration is invalid."""

    raw = os.getenv("AI_MAX_TEXT_CHARS")
    if raw is None:
        return DEFAULT_MAX_AI_TEXT_CHARS
    try:
        return max(500, int(raw))
    except ValueError:
        return DEFAULT_MAX_AI_TEXT_CHARS
