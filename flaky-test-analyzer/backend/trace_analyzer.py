"""Deterministic interpretation and compact summarization of normalized traces."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from backend.config import SLOW_REQUEST_THRESHOLD_MS, TRACE_TIMELINE_LIMIT


def _signal(items: list[dict[str, str]], kind: str, confidence: str, evidence: str) -> None:
    if not any(item["type"] == kind for item in items):
        items.append({"type": kind, "confidence": confidence, "evidence": evidence})


def analyze_trace(trace: dict[str, Any], timeline_limit: int = TRACE_TIMELINE_LIMIT) -> dict[str, Any]:
    actions = trace.get("actions") or []
    failed = next((a for a in reversed(actions) if a.get("error")), None)
    cutoff = actions.index(failed) + 1 if failed in actions else len(actions)
    relevant = actions[max(0, cutoff - max(1, timeline_limit)):cutoff]
    timeline = [{"sequence": a.get("index"), "action": a.get("api_name"), "selector": a.get("selector"),
                 "url": a.get("url"), "result": "failed" if a.get("error") else "success"} for a in relevant]
    problems = []
    for request in trace.get("network") or []:
        item = dict(request); status = item.get("status"); duration = item.get("duration_ms")
        if item.get("error"): item["problem"] = "failed_request"
        elif isinstance(status, int) and status >= 500: item["problem"] = "server_error"
        elif isinstance(status, int) and status >= 400: item["problem"] = "client_error"
        elif isinstance(duration, (int, float)) and duration >= SLOW_REQUEST_THRESHOLD_MS: item["problem"] = "slow_request"
        else: continue
        problems.append(item)
    signals: list[dict[str, str]] = []
    error = str((failed or {}).get("error") or ""); api = str((failed or {}).get("api_name") or ""); lower = error.lower()
    evidence = f"{api}: {error}".strip(": ")
    if "strict mode" in lower: _signal(signals, "strict_mode_violation", "high", evidence)
    if "not visible" in lower or "visible" in lower and "expect" in api.lower(): _signal(signals, "element_not_visible", "high", evidence)
    if "not found" in lower or "no element" in lower: _signal(signals, "locator_not_found", "high", evidence)
    if "timeout" in lower:
        _signal(signals, "navigation_timeout" if any(x in api.lower() for x in ("goto", "navigation", "wait_for_url", "load_state")) else "locator_timeout", "high", evidence)
    if "closed" in lower and any(x in lower for x in ("browser", "page", "context")): _signal(signals, "browser_or_page_closed", "high", evidence)
    selector = str((failed or {}).get("selector") or "")
    if selector and (selector.count(">") >= 3 or ":nth-child" in selector or selector.startswith("//")): _signal(signals, "brittle_selector", "medium", selector)
    for item in problems:
        detail = f"{item.get('method') or 'request'} {item.get('url')}"
        types = {"failed_request": "failed_network_request", "server_error": "http_5xx_before_failure", "client_error": "http_4xx_before_failure", "slow_request": "slow_request_before_failure"}
        _signal(signals, types[item["problem"]], "medium", detail)
    page_errors = (trace.get("page_errors") or [])[:20]
    if page_errors: _signal(signals, "page_error_before_failure", "medium", str(page_errors[-1].get("message")))
    if failed and not signals: _signal(signals, "unknown_trace_failure", "low", evidence)
    correlated = []
    failure_time = (failed or {}).get("end_time") or (failed or {}).get("start_time")
    if isinstance(failure_time, (int, float)):
        for item in problems:
            start = item.get("start_time"); duration = item.get("duration_ms") or 0
            if isinstance(start, (int, float)) and 0 <= failure_time - (start + duration) <= 5000:
                correlated.append({**item, "observation": "Network failure occurred close to the test failure."})
    return {"failed_action": failed, "actions_before_failure": timeline[:-1] if failed else timeline,
            "recent_actions": timeline, "network_problems": problems, "correlated_network_evidence": correlated,
            "page_errors": page_errors, "signals": signals}


def compact_trace_summary(analysis: dict[str, Any]) -> dict[str, Any]:
    failed = analysis.get("failed_action") or {}
    def short_url(value: str | None) -> str:
        if not value: return ""
        parts = urlsplit(value); return (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    return {"failed_action": " ".join(x for x in [failed.get("api_name"), failed.get("selector") or short_url(failed.get("url"))] if x) or None,
            "failure": failed.get("error"),
            "recent_actions": [" ".join(x for x in [a.get("action"), a.get("selector") or short_url(a.get("url"))] if x) for a in analysis.get("recent_actions", [])],
            "network_problems": [f"{n.get('method') or 'REQUEST'} {short_url(n.get('url'))} -> {n.get('status') or n.get('problem')}" for n in analysis.get("network_problems", [])],
            "page_errors": [x.get("message") for x in analysis.get("page_errors", [])],
            "signals": [x.get("type") for x in analysis.get("signals", [])]}
