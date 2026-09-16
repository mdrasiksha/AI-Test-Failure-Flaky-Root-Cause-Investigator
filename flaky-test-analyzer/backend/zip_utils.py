"""Bounded, extraction-free validation for untrusted Playwright ZIP archives."""

from __future__ import annotations

import io
import os
import stat
import zipfile
from pathlib import PurePosixPath

from backend.config import (
    MAX_TRACE_COMPRESSION_RATIO, MAX_TRACE_ENTRY_MB, MAX_TRACE_FILES,
    MAX_TRACE_UNCOMPRESSED_MB, MAX_TRACE_UPLOAD_MB,
)


class TraceArchiveError(ValueError):
    """A safe validation error for a trace archive."""


def open_safe_zip(data: bytes) -> zipfile.ZipFile:
    if len(data) > MAX_TRACE_UPLOAD_MB * 1024 * 1024:
        raise TraceArchiveError("Trace upload exceeds the configured size limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise TraceArchiveError("The uploaded file is not a valid ZIP archive") from exc
    if not entries:
        archive.close()
        raise TraceArchiveError("The trace ZIP is empty")
    if len(entries) > MAX_TRACE_FILES:
        archive.close(); raise TraceArchiveError("Trace ZIP contains too many files")
    total = sum(item.file_size for item in entries)
    if total > MAX_TRACE_UNCOMPRESSED_MB * 1024 * 1024:
        archive.close(); raise TraceArchiveError("Trace ZIP uncompressed content is too large")
    for item in entries:
        name = item.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
            archive.close(); raise TraceArchiveError("Trace ZIP contains an unsafe path")
        if item.file_size > MAX_TRACE_ENTRY_MB * 1024 * 1024:
            archive.close(); raise TraceArchiveError("Trace ZIP entry exceeds the size limit")
        ratio = item.file_size / max(1, item.compress_size)
        if ratio > MAX_TRACE_COMPRESSION_RATIO:
            archive.close(); raise TraceArchiveError("Trace ZIP has a suspicious compression ratio")
        mode = item.external_attr >> 16
        if mode and (stat.S_ISLNK(mode) or mode & 0o111):
            archive.close(); raise TraceArchiveError("Trace ZIP contains an executable or link entry")
    return archive


def safe_read(archive: zipfile.ZipFile, item: zipfile.ZipInfo) -> bytes:
    """Read one previously validated entry with a second streamed size bound."""
    limit = MAX_TRACE_ENTRY_MB * 1024 * 1024
    with archive.open(item) as source:
        value = source.read(limit + 1)
    if len(value) > limit:
        raise TraceArchiveError("Trace ZIP entry exceeds the size limit")
    return value
