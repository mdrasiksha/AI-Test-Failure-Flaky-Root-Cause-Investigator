"""Best-effort redaction and size limiting for evidence sent externally."""

from __future__ import annotations

import re
from typing import Any

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
