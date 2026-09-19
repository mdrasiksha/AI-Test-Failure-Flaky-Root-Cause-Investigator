"""FastAPI application for uploading and parsing JUnit XML reports."""

from io import BytesIO
import logging
import os
from pathlib import Path
import secrets
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from backend import analytics
from backend.ai_analyzer import AIAnalyzerError, AIConfigurationError, analyze_with_ai
from backend.classifier import classify_failure
from backend.config import (
    MAX_HISTORY_FILES,
    MAX_HISTORY_TOTAL_MB,
    MAX_TRACE_UPLOAD_MB,
    MAX_UPLOAD_MB,
    ai_analysis_enabled,
    max_ai_tests_per_request,
)
from backend.flaky_detector import analyze_history, get_test_id
from backend.parser import JUnitParseError, parse_junit_xml
from backend.playwright_analyzer import analyze_playwright_failure
from backend.trace_analyzer import analyze_trace, compact_trace_summary
from backend.trace_parser import parse_trace_zip
from backend.zip_utils import TraceArchiveError

app = FastAPI(title="Flaky Test Analyzer API")
_BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=_BASE_DIR / "frontend" / "static"), name="static")
templates = Jinja2Templates(directory=_BASE_DIR / "frontend" / "templates")
logger = logging.getLogger(__name__)

_SESSION_COOKIE = "anonymous_session_id"


def _record_event(*args: object, **kwargs: object) -> bool:
    """Keep analytics failures from affecting any analysis workflow."""
    try:
        return analytics.record_event(*args, **kwargs)
    except Exception:
        # The analytics module logs expected storage failures. This final guard
        # protects analysis if an unexpected analytics implementation fails.
        logger.warning("Unexpected product analytics failure")
        return False


def _session_days() -> int:
    try:
        return max(1, int(os.getenv("ANONYMOUS_SESSION_DAYS", "30")))
    except ValueError:
        return 30


analytics.initialize_storage()
analytics.cleanup_expired_events()


@app.middleware("http")
async def anonymous_product_analytics(request: Request, call_next):
    """Assign an opaque first-party session and record only route-level outcomes."""

    session_id = request.cookies.get(_SESSION_COOKIE)
    new_session = not session_id
    if new_session:
        session_id = secrets.token_urlsafe(24)
    request.state.anonymous_session_id = session_id

    path = request.url.path
    analysis_types = {
        "/upload-junit": "failure",
        "/analyze-ai": "failure",
        "/analyze-history": "history",
        "/analyze-trace": "trace",
        "/ui/analyze-junit": "failure",
        "/ui/analyze-history": "history",
        "/ui/analyze-trace": "trace",
        "/sample": "sample",
    }
    analysis_type = analysis_types.get(path) if request.method in {"GET", "POST"} else None
    if path == "/" and request.method == "GET":
        _record_event(session_id, "page_view")
    if path == "/sample" and request.method == "GET":
        _record_event(session_id, "sample_used", "sample")
    if analysis_type:
        _record_event(session_id, "analysis_started", analysis_type)
    direct_ai = ai_analysis_enabled() and (path == "/analyze-ai" or (
        path == "/analyze-trace" and request.query_params.get("use_ai", "false").lower() == "true"
    ))
    if direct_ai:
        _record_event(session_id, "ai_analysis_requested", analysis_type, True)

    try:
        response = await call_next(request)
    except Exception:
        if analysis_type:
            _record_event(session_id, "analysis_failed", analysis_type, direct_ai, False)
        raise
    if analysis_type:
        succeeded = response.status_code < 400
        _record_event(
            session_id,
            "analysis_completed" if succeeded else "analysis_failed",
            analysis_type,
            direct_ai if direct_ai else None,
            succeeded,
        )
        if succeeded and direct_ai:
            _record_event(session_id, "ai_analysis_completed", analysis_type, True, True)
    if new_session and analytics.analytics_enabled():
        response.set_cookie(
            _SESSION_COOKIE,
            session_id,
            max_age=_session_days() * 24 * 60 * 60,
            httponly=True,
            samesite="lax",
            secure=os.getenv("APP_ENV", "development").lower() == "production",
        )
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Apply browser hardening without blocking the same-origin Jinja UI."""

    content_length = request.headers.get("content-length")
    max_request_bytes = max(
        MAX_HISTORY_TOTAL_MB, MAX_TRACE_UPLOAD_MB + MAX_UPLOAD_MB
    ) * 1024 * 1024 + 1024 * 1024
    if content_length and content_length.isdigit() and int(content_length) > max_request_bytes:
        response = JSONResponse(
            status_code=413,
            content={"detail": "Request body exceeds the configured limit"},
        )
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Frame-Options"] = "DENY"
    return response


async def _read_limited(upload: UploadFile, limit_mb: int, label: str) -> bytes:
    """Read an upload in memory with an explicit byte limit."""

    limit = limit_mb * 1024 * 1024
    content = await upload.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{label} exceeds the configured {limit_mb} MB upload limit",
        )
    return content


def _upload(data: bytes, filename: str, content_type: str) -> UploadFile:
    """Create an in-memory upload when a UI workflow reuses safe input bytes."""
    return UploadFile(BytesIO(data), filename=filename, headers={"content-type": content_type})


def _friendly_detail(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        if detail.get("code") == "ai_not_configured":
            return "AI analysis is not configured. You can continue using deterministic analysis."
        return str(detail.get("message") or "The analysis service is unavailable.")
    return str(detail)


def _error_page(request: Request, message: str, status_code: int = 400) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"message": message},
        status_code=status_code,
    )


async def _run_ai(evidence: dict[str, object]) -> dict[str, object]:
    try:
        return await run_in_threadpool(analyze_with_ai, evidence)
    except AIConfigurationError as exc:
        raise HTTPException(
            status_code=503, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except AIAnalyzerError as exc:
        raise HTTPException(
            status_code=502, detail={"code": exc.code, "message": str(exc)}
        ) from exc


def build_ai_evidence(
    test: dict[str, object],
    classification: dict[str, object],
    framework_analysis: dict[str, object] | None,
) -> dict[str, object]:
    """Select only failure evidence relevant to an AI investigation."""

    evidence: dict[str, object] = {
        "test_id": get_test_id(test),
        "test_name": test["test_name"],
        "status": test["status"],
        "error": {
            "type": test.get("error_type"),
            "message": test.get("error_message"),
            "stack_trace": test.get("stack_trace"),
        },
        "generic_classification": classification,
    }
    if framework_analysis is not None:
        evidence["playwright_analysis"] = framework_analysis
    return evidence


@app.get("/", response_class=HTMLResponse)
def root(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"ai_analysis_enabled": ai_analysis_enabled()},
    )


@app.get("/api")
def api_info() -> dict[str, str]:
    return {"message": "Flaky Test Analyzer API", "docs": "/docs"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "flaky-test-analyzer"}


@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="privacy.html")


class FeedbackSubmission(BaseModel):
    """Strict feedback input with no diagnostic or identity fields."""

    model_config = ConfigDict(extra="forbid")
    useful: StrictBool
    feedback_text: str | None = Field(default=None, max_length=500)
    analysis_type: Literal["failure", "history", "trace", "sample"] | None = None


@app.post("/feedback")
def submit_feedback(request: Request, submission: FeedbackSubmission) -> dict[str, str]:
    if not analytics.analytics_enabled():
        raise HTTPException(status_code=503, detail="Feedback is currently unavailable")
    saved = analytics.record_feedback(
        request.state.anonymous_session_id,
        submission.useful,
        submission.feedback_text,
        submission.analysis_type,
    )
    if not saved:
        raise HTTPException(status_code=503, detail="Feedback is currently unavailable")
    return {"message": "Thanks for the feedback."}


@app.get("/internal/metrics")
def internal_metrics(
    days: int = Query(default=7, ge=1, le=90),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, object]:
    configured_token = os.getenv("ADMIN_METRICS_TOKEN")
    if not configured_token:
        raise HTTPException(status_code=404, detail="Not found")
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, configured_token):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    if not analytics.analytics_enabled():
        raise HTTPException(status_code=503, detail="Analytics is disabled")
    try:
        return analytics.aggregate_metrics(days)
    except (analytics.AnalyticsStorageError, ValueError):
        raise HTTPException(status_code=503, detail="Metrics are unavailable") from None


@app.post("/analyze-trace")
async def analyze_trace_upload(
    trace_file: UploadFile | None = File(default=None),
    junit_file: UploadFile | None = File(default=None),
    use_ai: bool = False,
) -> dict[str, object]:
    """Safely inspect a trace ZIP and optionally combine it with JUnit evidence."""
    if trace_file is None or not trace_file.filename:
        if trace_file:
            await trace_file.close()
        if junit_file:
            await junit_file.close()
        raise HTTPException(status_code=400, detail="A Playwright trace ZIP is required")
    try:
        content = await _read_limited(trace_file, MAX_TRACE_UPLOAD_MB, "Trace upload")
        normalized = parse_trace_zip(content, trace_file.filename)
    except TraceArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await trace_file.close()
    analysis = analyze_trace(normalized)
    combined = None
    if junit_file is not None and junit_file.filename:
        try:
            raw = await _read_limited(junit_file, MAX_UPLOAD_MB, "JUnit upload")
            junit_results = parse_junit_xml(raw)
        except JUnitParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            await junit_file.close()
        failures = [
            test for test in junit_results if test["status"] in {"failed", "error"}
        ]
        combined = [
            {
                **test,
                "classification": classify_failure(test),
                "framework_analysis": analyze_playwright_failure(test),
            }
            for test in failures
        ]
    elif junit_file is not None:
        await junit_file.close()
    summary = compact_trace_summary(analysis)
    ai_analysis = None
    if use_ai and ai_analysis_enabled():
        evidence: dict[str, object] = {
            "test_name": (combined or [{}])[0].get("test_name")
            or "unknown trace test",
            "trace_analysis": summary,
        }
        if combined:
            evidence["junit_analysis"] = combined
        ai_analysis = await _run_ai(evidence)
    return {
        "trace": {"valid": True, **normalized["inventory"]},
        "analysis": analysis,
        "junit_analysis": combined,
        "mapping_note": (
            "Trace-to-JUnit mapping is uncertain; evidence was combined without "
            "asserting identity."
            if combined
            else None
        ),
        "ai_evidence": summary,
        "ai_analysis": ai_analysis,
    }


@app.post("/upload-junit")
async def upload_junit(
    file: UploadFile | None = File(default=None),
) -> dict[str, object]:
    """Parse an uploaded JUnit report without persisting it."""

    if file is None or not file.filename:
        if file:
            await file.close()
        raise HTTPException(status_code=400, detail="A JUnit XML file is required")

    try:
        content = await _read_limited(file, MAX_UPLOAD_MB, "JUnit upload")
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded XML file is empty")
        tests = parse_junit_xml(content)
    except JUnitParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()

    if not tests:
        raise HTTPException(
            status_code=400, detail="The JUnit XML contains no testcases"
        )

    response_tests = [
        {
            **test,
            "classification": (
                classify_failure(test)
                if test["status"] in {"failed", "error"}
                else None
            ),
            "framework_analysis": (
                analyze_playwright_failure(test)
                if test["status"] in {"failed", "error"}
                else None
            ),
        }
        for test in tests
    ]

    counts = {
        status: sum(test["status"] == status for test in tests)
        for status in ("passed", "failed", "error", "skipped")
    }
    return {
        "total_tests": len(tests),
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["error"],
        "skipped": counts["skipped"],
        "tests": response_tests,
    }


@app.post("/analyze-history")
async def analyze_junit_history(
    files: list[UploadFile] | None = File(default=None),
) -> dict[str, object]:
    """Analyze multiple JUnit reports in their multipart upload order."""

    if not files:
        raise HTTPException(
            status_code=400, detail="At least one JUnit XML file is required"
        )
    if len(files) > MAX_HISTORY_FILES:
        for file in files:
            await file.close()
        raise HTTPException(
            status_code=413,
            detail=f"History upload is limited to {MAX_HISTORY_FILES} reports",
        )

    runs = []
    total_bytes = 0
    try:
        for position, file in enumerate(files, start=1):
            filename = file.filename or f"file {position}"
            content = await _read_limited(file, MAX_UPLOAD_MB, "JUnit upload")
            total_bytes += len(content)
            if total_bytes > MAX_HISTORY_TOTAL_MB * 1024 * 1024:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "Combined history uploads exceed the configured "
                        f"{MAX_HISTORY_TOTAL_MB} MB limit"
                    ),
                )
            if not content:
                raise HTTPException(
                    status_code=400, detail=f"History file '{filename}' is empty"
                )
            try:
                tests = parse_junit_xml(content)
            except JUnitParseError as exc:
                raise HTTPException(
                    status_code=400, detail=f"Invalid history file '{filename}': {exc}"
                ) from exc
            if not tests:
                raise HTTPException(
                    status_code=400,
                    detail=f"History file '{filename}' contains no testcases",
                )
            runs.append(tests)
    finally:
        # UploadFile may use a spooled temporary file. Close every part even when
        # an earlier report fails validation so no temporary upload survives.
        for file in files:
            await file.close()

    tests = analyze_history(runs)
    latest_failures = {}
    for run in runs:
        for result in run:
            if result["status"] in {"failed", "error"}:
                latest_failures[get_test_id(result)] = analyze_playwright_failure(
                    result
                )
    for test in tests:
        test["latest_failure_analysis"] = latest_failures.get(test["test_id"])
    return {
        "runs_analyzed": len(runs),
        "tests_analyzed": len(tests),
        "flaky_tests": sum(
            test["flaky_status"] in {"possible", "high"} for test in tests
        ),
        "tests": tests,
    }


@app.post("/analyze-ai")
async def analyze_ai(file: UploadFile | None = File(default=None)) -> dict[str, object]:
    """Run optional AI investigation for each failed/error testcase."""

    if file is None or not file.filename:
        if file:
            await file.close()
        raise HTTPException(status_code=400, detail="A JUnit XML file is required")
    try:
        content = await _read_limited(file, MAX_UPLOAD_MB, "JUnit upload")
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded XML file is empty")
        tests = parse_junit_xml(content)
    except JUnitParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
    if not tests:
        raise HTTPException(
            status_code=400, detail="The JUnit XML contains no testcases"
        )

    results: list[dict[str, object]] = []
    enabled = ai_analysis_enabled()
    ai_limit = max_ai_tests_per_request() if enabled else 0
    failures_seen = 0
    for test in tests:
        if test["status"] not in {"failed", "error"}:
            continue
        classification = classify_failure(test)
        framework_analysis = analyze_playwright_failure(test)
        failures_seen += 1
        ai_analysis = None
        if enabled and failures_seen <= ai_limit:
            evidence = build_ai_evidence(test, classification, framework_analysis)
            ai_analysis = await _run_ai(evidence)
        results.append(
            {
                "test_name": test["test_name"],
                "status": test["status"],
                "classification": classification,
                "framework_analysis": framework_analysis,
                "ai_analysis": ai_analysis,
                "ownership_note": "ownership_hint is advisory investigative guidance, not proof of ownership.",
            }
        )
    if not results:
        # Retain the established no-failure response shape; no AI limit applies.
        return {"total_tests": len(tests), "failures_analyzed": 0, "tests": []}
    return {
        "total_tests": len(tests),
        "failures_analyzed": min(len(results), ai_limit),
        "total_failures": len(results),
        "ai_limit": ai_limit,
        "ai_analysis_limited": enabled and len(results) > ai_limit,
        "ai_limit_message": (
            f"AI analysis was limited to {ai_limit} of {len(results)} failures; "
            "deterministic analysis is included for every failure."
            if enabled and len(results) > ai_limit else None
        ),
        "tests": results,
    }


@app.post("/ui/analyze-junit", response_class=HTMLResponse)
async def ui_analyze_junit(
    request: Request,
    file: UploadFile | None = File(default=None),
    use_ai: bool = Form(default=False),
) -> HTMLResponse:
    if file is None or not file.filename:
        if file:
            await file.close()
        return _error_page(request, "Choose a JUnit XML file to analyze.")
    filename = Path(file.filename).name
    try:
        data = await _read_limited(file, MAX_UPLOAD_MB, "JUnit upload")
    except HTTPException as exc:
        return _error_page(request, _friendly_detail(exc), exc.status_code)
    finally:
        await file.close()
    if not filename.lower().endswith(".xml"):
        return _error_page(request, "JUnit reports must use the .xml extension.")
    try:
        result = await upload_junit(_upload(data, filename, "application/xml"))
        if use_ai and ai_analysis_enabled():
            _record_event(
                request.state.anonymous_session_id, "ai_analysis_requested", "failure", True
            )
            ai_result = await analyze_ai(_upload(data, filename, "application/xml"))
            by_name = {item["test_name"]: item for item in ai_result["tests"]}
            for test in result["tests"]:
                if test["test_name"] in by_name:
                    test["ai_analysis"] = by_name[test["test_name"]]["ai_analysis"]
            _record_event(
                request.state.anonymous_session_id,
                "ai_analysis_completed", "failure", True, True,
            )
    except HTTPException as exc:
        return _error_page(request, _friendly_detail(exc), exc.status_code)
    return templates.TemplateResponse(request=request, name="report.html", context={
        "title": "Test Failure Analysis", "mode": "junit", "result": result,
        "items": result["tests"],
    })


@app.post("/ui/analyze-history", response_class=HTMLResponse)
async def ui_analyze_history(
    request: Request, files: list[UploadFile] | None = File(default=None)
) -> HTMLResponse:
    files = files or []
    if len(files) < 2:
        for item in files:
            await item.close()
        return _error_page(request, "Upload at least two JUnit XML files in chronological order.")
    if any(not (item.filename or "").lower().endswith(".xml") for item in files):
        for item in files:
            await item.close()
        return _error_page(request, "Every history report must use the .xml extension.")
    try:
        result = await analyze_junit_history(files)
    except HTTPException as exc:
        return _error_page(request, _friendly_detail(exc), exc.status_code)
    return templates.TemplateResponse(request=request, name="report.html", context={
        "title": "Flaky History Analysis", "mode": "history", "result": result,
        "items": result["tests"],
    })


@app.post("/ui/analyze-trace", response_class=HTMLResponse)
async def ui_analyze_trace(
    request: Request,
    trace_file: UploadFile | None = File(default=None),
    junit_file: UploadFile | None = File(default=None),
    use_ai: bool = Form(default=False),
) -> HTMLResponse:
    if trace_file is None or not trace_file.filename:
        if trace_file:
            await trace_file.close()
        if junit_file:
            await junit_file.close()
        return _error_page(request, "Choose a Playwright trace ZIP to analyze.")
    if not trace_file.filename.lower().endswith(".zip"):
        await trace_file.close()
        if junit_file:
            await junit_file.close()
        return _error_page(request, "Playwright traces must use the .zip extension.")
    if junit_file and junit_file.filename and not junit_file.filename.lower().endswith(".xml"):
        await trace_file.close()
        await junit_file.close()
        return _error_page(request, "The optional JUnit report must use the .xml extension.")
    try:
        if use_ai and ai_analysis_enabled():
            _record_event(
                request.state.anonymous_session_id, "ai_analysis_requested", "trace", True
            )
        effective_use_ai = use_ai and ai_analysis_enabled()
        result = await analyze_trace_upload(trace_file, junit_file, effective_use_ai)
        if effective_use_ai:
            _record_event(
                request.state.anonymous_session_id,
                "ai_analysis_completed", "trace", True, True,
            )
    except HTTPException as exc:
        return _error_page(request, _friendly_detail(exc), exc.status_code)
    return templates.TemplateResponse(request=request, name="report.html", context={
        "title": "Playwright Trace Analysis", "mode": "trace", "result": result,
        "items": result.get("junit_analysis") or [],
    })


@app.get("/sample", response_class=HTMLResponse)
async def sample_report(request: Request) -> HTMLResponse:
    sample = _BASE_DIR / "sample_data" / "playwright" / "locator_timeout.xml"
    result = await upload_junit(_upload(sample.read_bytes(), sample.name, "application/xml"))
    return templates.TemplateResponse(request=request, name="report.html", context={
        "title": "Sample: Playwright Locator Timeout", "mode": "junit",
        "result": result, "items": result["tests"], "is_sample": True,
    })
