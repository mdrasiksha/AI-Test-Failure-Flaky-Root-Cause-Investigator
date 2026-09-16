"""FastAPI application for uploading and parsing JUnit XML reports."""

from fastapi import FastAPI, File, HTTPException, UploadFile

from backend.classifier import classify_failure
from backend.flaky_detector import analyze_history, get_test_id
from backend.parser import JUnitParseError, parse_junit_xml
from backend.playwright_analyzer import analyze_playwright_failure

app = FastAPI(title="Flaky Test Analyzer API")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Flaky Test Analyzer API"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
                latest_failures[get_test_id(result)] = analyze_playwright_failure(result)
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
