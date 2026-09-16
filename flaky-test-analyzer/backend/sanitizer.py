"""Best-effort redaction and size limiting for evidence sent externally."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"

_PATTERNS = (
    # Preserve the authentication scheme so the resulting evidence remains useful.
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"), r"\1" + REDACTED),
    (re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + REDACTED),
    (
        re.compile(
            r"(?i)((?:password|passwd|pwd|api[_-]?key|secret(?:[_-]?key)?|session[_-]?token|access[_-]?token)\s*[:=]\s*)[^\s,;]+"
        ),
        r"\1" + REDACTED,
    ),
    (re.compile(r"(?i)((?:cookie|set-cookie)\s*:\s*)[^\r\n]+"), r"\1" + REDACTED),
)
SENSITIVE_QUERY_KEYS = frozenset(
    {"token", "access_token", "key", "api_key", "password", "session", "auth", "code"}
)


def sanitize_url(value: str) -> str:
    """Redact common secret-bearing query parameters while preserving URL utility."""
    try:
        parts = urlsplit(value)
        query = urlencode(
            [(key, REDACTED if key.lower() in SENSITIVE_QUERY_KEYS else item) for key, item in parse_qsl(parts.query, keep_blank_values=True)],
            doseq=True,
            safe="[]",
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except (TypeError, ValueError):
        return sanitize_text(value)


def sanitize_text(value: str, max_chars: int | None = None) -> str:
    """Redact common secret shapes, de-duplicate lines, and optionally truncate.

    This is deliberately a small best-effort safeguard, not a guarantee that all
    sensitive information can be identified.
    """

    sanitized = value
    for pattern, replacement in _PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    lines: list[str] = []
    previous: str | None = None
    for line in sanitized.splitlines(keepends=True):
        if line == previous:
            continue
        lines.append(line)
        previous = line
    sanitized = "".join(lines)

    if max_chars is not None and len(sanitized) > max_chars:
        marker = "\n...[TRUNCATED]"
        sanitized = sanitized[: max(0, max_chars - len(marker))] + marker
    return sanitized


def sanitize_evidence(value: Any, max_text_chars: int) -> Any:
    """Return a recursively sanitized copy of structured evidence."""

    if isinstance(value, str):
        return sanitize_text(value, max_text_chars)
    if isinstance(value, dict):
        return {
            key: sanitize_evidence(item, max_text_chars) for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_evidence(item, max_text_chars) for item in value]
    return value
