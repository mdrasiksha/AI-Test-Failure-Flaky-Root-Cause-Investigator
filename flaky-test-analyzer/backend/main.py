"""FastAPI application for uploading and parsing JUnit XML reports."""

from fastapi import FastAPI, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.ai_analyzer import AIAnalyzerError, AIConfigurationError, analyze_with_ai
from backend.classifier import classify_failure
from backend.config import MAX_TRACE_UPLOAD_MB
from backend.flaky_detector import analyze_history, get_test_id
from backend.parser import JUnitParseError, parse_junit_xml
from backend.playwright_analyzer import analyze_playwright_failure
from backend.trace_analyzer import analyze_trace, compact_trace_summary
from backend.trace_parser import parse_trace_zip
from backend.zip_utils import TraceArchiveError

app = FastAPI(title="Flaky Test Analyzer API")


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


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Flaky Test Analyzer API"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze-trace")
async def analyze_trace_upload(
    trace_file: UploadFile | None = File(default=None),
    junit_file: UploadFile | None = File(default=None),
    use_ai: bool = False,
) -> dict[str, object]:
    """Safely inspect a trace ZIP and optionally combine it with JUnit evidence."""
    if trace_file is None or not trace_file.filename:
        raise HTTPException(status_code=400, detail="A Playwright trace ZIP is required")
    try:
        content = await trace_file.read(MAX_TRACE_UPLOAD_MB * 1024 * 1024 + 1)
        normalized = parse_trace_zip(content, trace_file.filename)
    except TraceArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await trace_file.close()
    analysis = analyze_trace(normalized)
    combined = None
    if junit_file is not None and junit_file.filename:
        try:
            raw = await junit_file.read()
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
    summary = compact_trace_summary(analysis)
    ai_analysis = None
    if use_ai:
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
        raise HTTPException(status_code=400, detail="A JUnit XML file is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded XML file is empty")

    try:
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

    runs = []
    for position, file in enumerate(files, start=1):
        filename = file.filename or f"file {position}"
        try:
            content = await file.read()
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
        raise HTTPException(status_code=400, detail="A JUnit XML file is required")
    content = await file.read()
    await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded XML file is empty")
    try:
        tests = parse_junit_xml(content)
    except JUnitParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not tests:
        raise HTTPException(
            status_code=400, detail="The JUnit XML contains no testcases"
        )

    results: list[dict[str, object]] = []
    for test in tests:
        if test["status"] not in {"failed", "error"}:
            continue
        classification = classify_failure(test)
        framework_analysis = analyze_playwright_failure(test)
        evidence = build_ai_evidence(test, classification, framework_analysis)
        try:
            ai_analysis = await run_in_threadpool(analyze_with_ai, evidence)
        except AIConfigurationError as exc:
            raise HTTPException(
                status_code=503, detail={"code": exc.code, "message": str(exc)}
            ) from exc
        except AIAnalyzerError as exc:
            raise HTTPException(
                status_code=502, detail={"code": exc.code, "message": str(exc)}
            ) from exc
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
    return {
        "total_tests": len(tests),
        "failures_analyzed": len(results),
        "tests": results,
    }
