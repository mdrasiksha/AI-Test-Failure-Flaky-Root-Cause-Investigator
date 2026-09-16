# Flaky Test Analyzer

This MVP is a FastAPI service that parses JUnit XML, classifies failures with
deterministic rules, and detects historically inconsistent test outcomes. It
does not use AI/LLMs or assign statistical probabilities.

## Local setup

Run these commands from the repository root on macOS/Linux:

```bash
cd flaky-test-analyzer
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
pytest -v
uvicorn backend.main:app --reload
```

On Windows Command Prompt or PowerShell, replace the activation command with:

```bat
venv\Scripts\activate
```

The API runs at <http://127.0.0.1:8000>, and its interactive Swagger UI is at
<http://127.0.0.1:8000/docs>.

## Analyze one JUnit report

`POST /upload-junit` accepts one XML file using the multipart field `file`. It
returns status totals and normalized tests. Failed/error tests include a
rule-based `classification`; passed/skipped tests have `classification: null`.

With Swagger:

1. Open <http://127.0.0.1:8000/docs>.
2. Expand **POST /upload-junit** and select **Try it out**.
3. Choose `sample_data/junit.xml` and select **Execute**.

Or use curl:

```bash
curl -X POST http://127.0.0.1:8000/upload-junit \
  -F "file=@sample_data/junit.xml"
```

## Analyze historical runs

`POST /analyze-history` accepts multiple XML files using the multipart field
`files`. File selection/upload order is treated as chronological run order.

With Swagger:

1. Open <http://127.0.0.1:8000/docs>.
2. Expand **POST /analyze-history** and select **Try it out**.
3. In the `files` picker, select all five files in `sample_data/history/`
   (`run1.xml` through `run5.xml`) together, in chronological order.
4. Select **Execute**. The sample reports show `test_login` as stable,
   `test_payment` as high, and `test_checkout` as consistently failing.

Or use curl:

```bash
curl -X POST http://127.0.0.1:8000/analyze-history \
  -F "files=@sample_data/history/run1.xml" \
  -F "files=@sample_data/history/run2.xml" \
  -F "files=@sample_data/history/run3.xml" \
  -F "files=@sample_data/history/run4.xml" \
  -F "files=@sample_data/history/run5.xml"
```

## Flaky-test heuristic

Tests are identified by `classname::test_name` (or just `test_name` when no
classname exists). Skipped outcomes do not affect failure rate or transitions.
Fewer than three executed results normally means insufficient history; all
passes are stable and all failures/errors are consistently failing. A history
containing both pass and failure outcomes is `possible`, or `high` with at least
five executions and two pass/failure transitions. A pass-only history spanning
at least three appearances remains stable even when some appearances are
skipped.

These labels are a deterministic MVP heuristic based on observed statuses—not
a machine-learning, AI, or statistical probability.

## API endpoints

- `GET /` returns the API name.
- `GET /health` returns a basic health status.
- `POST /upload-junit` parses and classifies one JUnit XML report.
- `POST /analyze-history` analyzes multiple chronological JUnit XML reports.

Reports are parsed in memory and are not stored.
