"""Version-tolerant normalization of Playwright trace JSON-lines artifacts."""

from __future__ import annotations

import json
from typing import Any

from backend.sanitizer import sanitize_text, sanitize_url
from backend.zip_utils import TraceArchiveError, open_safe_zip, safe_read

TEXT_LIMIT = 1000


def _text(value: Any) -> str | None:
    if value is None: return None
    if isinstance(value, dict): value = value.get("message") or value.get("value") or json.dumps(value)
    return sanitize_text(str(value), TEXT_LIMIT)


def _number(value: Any) -> float | None:
    try: return float(value) if value is not None else None
    except (TypeError, ValueError): return None


def _url(value: Any) -> str | None:
    return sanitize_url(str(value))[:TEXT_LIMIT] if value else None


def _records(raw: bytes) -> list[dict[str, Any]]:
    found = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try: value = json.loads(line)
        except (json.JSONDecodeError, TypeError): continue
        if isinstance(value, dict): found.append(value)
    return found


def _action(record: dict[str, Any], index: int) -> dict[str, Any]:
    params = record.get("params") if isinstance(record.get("params"), dict) else {}
    api = record.get("apiName") or record.get("api_name") or record.get("method") or record.get("title")
    cls = record.get("class") or record.get("objectType")
    if cls and api and "." not in str(api): api = f"{str(cls).lower()}.{api}"
    start = _number(record.get("startTime") or record.get("start_time") or record.get("time"))
    end = _number(record.get("endTime") or record.get("end_time"))
    duration = _number(record.get("duration") or record.get("duration_ms"))
    if duration is None and start is not None and end is not None: duration = end - start
    selector = params.get("selector") or params.get("locator") or record.get("selector")
    url = params.get("url") or record.get("url")
    allowed = {k: _text(v) for k, v in params.items() if k.lower() in {"selector", "locator", "url", "name", "value"}}
    return {"index": index, "api_name": _text(api), "start_time": start, "end_time": end,
            "duration_ms": duration, "url": _url(url), "selector": _text(selector),
            "error": _text(record.get("error")), "parameters": allowed}


def _network(record: dict[str, Any]) -> dict[str, Any] | None:
    snap = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else record
    request = snap.get("request") if isinstance(snap.get("request"), dict) else {}
    response = snap.get("response") if isinstance(snap.get("response"), dict) else {}
    url = request.get("url") or snap.get("url")
    if not url: return None
    start = _number(snap.get("timestamp") or snap.get("startTime") or record.get("time"))
    duration = _number(snap.get("duration") or snap.get("duration_ms"))
    timings = snap.get("timings")
    if duration is None and isinstance(timings, dict):
        values = [_number(v) for v in timings.values()]; duration = sum(v for v in values if v and v > 0) or None
    return {"method": _text(request.get("method") or snap.get("method")), "url": _url(url),
            "resource_type": _text(snap.get("resourceType") or record.get("resourceType")),
            "status": response.get("status") if isinstance(response.get("status"), int) else snap.get("status"),
            "start_time": start, "duration_ms": duration,
            "error": _text(snap.get("failure") or snap.get("error") or response.get("error"))}


def parse_trace_zip(data: bytes, filename: str = "trace.zip") -> dict[str, Any]:
    archive = open_safe_zip(data)
    try:
        entries = archive.infolist()
        traces = [x for x in entries if x.filename.lower().endswith((".trace", "trace.jsonl"))]
        networks = [x for x in entries if x.filename.lower().endswith((".network", "network.jsonl"))]
        inventory = {"filename": filename, "entry_count": len(entries),
                     "trace_files_found": [x.filename for x in traces], "network_files_found": [x.filename for x in networks],
                     "resource_files_found": sum("resources/" in x.filename.lower() and not x.is_dir() for x in entries)}
        if not traces and not networks: raise TraceArchiveError("ZIP contains no supported Playwright trace data")
        records = [r for item in traces for r in _records(safe_read(archive, item))]
        netrecords = [r for item in networks for r in _records(safe_read(archive, item))]
    finally: archive.close()
    actions: list[dict[str, Any]] = []; pending: dict[str, dict[str, Any]] = {}; errors = []; page_errors = []
    for record in records:
        kind = str(record.get("type", "")).lower(); call_id = str(record.get("callId") or record.get("id") or "")
        if kind in {"before", "action"} or record.get("apiName"):
            action = _action(record, len(actions) + 1); actions.append(action)
            if call_id: pending[call_id] = action
        elif kind == "after" and call_id in pending:
            action = pending[call_id]; action["end_time"] = _number(record.get("endTime") or record.get("time")); action["error"] = _text(record.get("error"))
            if action["duration_ms"] is None and action["start_time"] is not None and action["end_time"] is not None: action["duration_ms"] = action["end_time"] - action["start_time"]
        if kind in {"pageerror", "console"} and (kind == "pageerror" or str(record.get("messageType", record.get("level", ""))).lower() == "error"):
            item = {"message": _text(record.get("error") or record.get("message") or record.get("text")), "time": _number(record.get("time"))}
            if item["message"]: page_errors.append(item)
        if record.get("error"): errors.append({"message": _text(record["error"]), "time": _number(record.get("time") or record.get("endTime"))})
    network = [item for record in netrecords for item in [_network(record)] if item]
    return {"framework": "playwright", "inventory": inventory, "actions": actions, "errors": errors[:50], "network": network[:500], "page_errors": page_errors[:50], "pages": [], "metadata": {"malformed_or_unsupported_records_ignored": True}}
