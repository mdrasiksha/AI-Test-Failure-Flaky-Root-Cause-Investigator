"""FastAPI application for uploading and parsing JUnit XML reports."""

from fastapi import FastAPI, File, HTTPException, UploadFile

from backend.parser import JUnitParseError, parse_junit_xml

app = FastAPI(title="Flaky Test Analyzer API")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Flaky Test Analyzer API"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/upload-junit")
async def upload_junit(file: UploadFile | None = File(default=None)) -> dict[str, object]:
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

    counts = {status: sum(test["status"] == status for test in tests) for status in ("passed", "failed", "error", "skipped")}
    return {
        "total_tests": len(tests),
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["error"],
        "skipped": counts["skipped"],
        "tests": tests,
    }
