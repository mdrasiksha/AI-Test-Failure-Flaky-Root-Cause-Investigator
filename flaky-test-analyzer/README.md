# Flaky Test Analyzer

This MVP is a FastAPI service that parses JUnit XML, classifies failures with
deterministic rules, detects historically inconsistent test outcomes, and can
optionally request an advisory AI root-cause investigation. Deterministic
analysis remains available without an AI provider. AI confidence is qualitative,
not a statistical probability.

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

For production and Docker startup, environment variables, upload limits, and
HTTPS guidance, see [DEPLOYMENT.md](DEPLOYMENT.md).

## Web Interface

The server root is now a small, server-rendered QA application. After setup,
start it and open <http://127.0.0.1:8000>:

```bash
python -m venv venv
# Windows Command Prompt or PowerShell:
venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

On macOS/Linux, activate with `source venv/bin/activate` instead. The interface
provides four focused workflows:

- **Test Failure** uploads one JUnit XML report for deterministic classification
  and Playwright-specific guidance. AI investigation is an optional checkbox.
- **Flaky History** accepts multiple chronological JUnit XML reports and displays
  observed outcomes, failure rate, transitions, and the heuristic flaky status.
- **Playwright Trace** accepts `trace.zip`, an optional JUnit XML report, and an
  optional AI investigation. The report highlights the action timeline, trace
  signals, and network problems without extracting or executing uploaded files.
- **Try Sample** immediately analyzes the safe synthetic Playwright locator-timeout
  report in `sample_data/playwright/locator_timeout.xml`; no upload is needed.

Reports organize findings into QA-oriented cards, with expandable technical
information and escaped raw JSON for debugging. Uploaded content is rendered as
text, never trusted HTML. AI remains optional: if it is not configured, all
regular deterministic workflows remain available. When trace AI analysis is
selected, only compact sanitized diagnostic evidence is sent to the configured
provider; the raw ZIP and binary resources are never sent.

The interactive API documentation remains available at
<http://127.0.0.1:8000/docs>, and `GET /api` provides basic API information.

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

- `GET /` renders the web interface.
- `GET /api` returns basic API information.
- `GET /health` returns a basic, secret-free service health status.
- `POST /upload-junit` parses and classifies one JUnit XML report.
- `POST /analyze-history` analyzes multiple chronological JUnit XML reports.
- `POST /analyze-ai` optionally investigates failed tests with an AI provider.

Reports are parsed in memory and are not stored.

## Playwright Failure Analysis

Failed and errored Playwright tests also receive a `framework_analysis`. This
analysis uses deterministic, explicitly prioritized rules—not AI or an LLM—to
identify Playwright-specific locator, actionability, assertion, navigation,
network, browser lifecycle, selector, and API-response failures. Non-Playwright
failures return `framework_analysis: null`.

For example, this JUnit failure text:

```text
TimeoutError: locator.click: Timeout 5000ms exceeded
Call log:
waiting for get_by_role("button", name="Pay")
```

produces analysis including:

```json
{
  "framework": "playwright",
  "issue_type": "locator_not_found",
  "category": "locator",
  "confidence": "high",
  "timeout_increase_recommended": false,
  "metadata": {
    "action": "locator.click",
    "timeout_ms": 5000,
    "locator": "get_by_role(\"button\", name=\"Pay\")"
  }
}
```

Try it with `sample_data/playwright/locator_timeout.xml`. The analyzer advises
investigating the locator and meaningful application state first. It does not
automatically recommend increasing global timeouts, `page.wait_for_timeout`, or
fixed sleeps, because these workarounds can hide the underlying problem and
slow the suite. A timeout increase may be appropriate for a genuinely slow
operation only after that underlying behavior has been investigated.

## AI Root-Cause Analysis

The optional `POST /analyze-ai` endpoint accepts one JUnit XML file in the
multipart field `file`. It analyzes each failed or errored testcase separately;
passed and skipped tests do not cause an AI request. The response preserves the
generic classification and Playwright analysis alongside the AI investigation.

Copy the example environment file, add your own key, and optionally select a
different model:

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY. Never commit this file.
uvicorn backend.main:app --reload
```

Open <http://127.0.0.1:8000/docs>, expand **POST /analyze-ai**, choose (for
example) `sample_data/playwright/locator_timeout.xml`, and select **Execute**.
The existing `/upload-junit` and `/analyze-history` endpoints continue to work
when `OPENAI_API_KEY` is absent. `/analyze-ai` returns a controlled configuration
error until a key is configured.

Only a compact evidence object is sent: testcase identity/name/status; failure
type, message, and stack trace; the generic deterministic classification; and,
when detected, the deterministic Playwright analysis. A single-report request
does not invent or send history that is unavailable. It does not send the whole
JUnit document or unrelated application data.

Before transmission, obvious authorization values, bearer tokens, API keys,
passwords, cookies, and session/access tokens are redacted on a best-effort
basis. Consecutive duplicate lines are removed, and each text field is limited
to `AI_MAX_TEXT_CHARS` (12,000 by default) with an explicit truncation marker.
These safeguards are intentionally configurable and do **not** guarantee that
every possible secret will be found.

> **Privacy warning:** Review logs and test artifacts before sending them to an
> external AI provider because they may contain sensitive information.

AI analysis is advisory, may be incorrect, and is based only on available
evidence. It should not replace engineering investigation. In particular,
`ownership_hint` is an investigative hint—not proof that a failure belongs to
QA, development, infrastructure, or any other team.

At most `MAX_AI_TESTS_PER_REQUEST` failed tests (five by default) are sent to the
provider in one request. If a report has more failures, every failure still gets
deterministic classification and the response explicitly reports the AI limit.

## Playwright Trace Analysis

Step 7 adds bounded, extraction-free analysis of Playwright `trace.zip` files. Start
tracing in Python Playwright and save the archive when the test finishes:

```python
context.tracing.start(screenshots=True, snapshots=True, sources=True)
# ... run the test ...
context.tracing.stop(path="trace.zip")
```

A pytest-playwright configuration may already retain traces, depending on its trace
settings. Open `http://127.0.0.1:8000/docs` and use `POST /analyze-trace` with:

- `trace_file`: required Playwright ZIP;
- `junit_file`: optional JUnit XML. The API combines the evidence but explicitly
  reports that trace-to-test mapping is uncertain;
- `use_ai=false` (the default): deterministic parsing and rules only; or
- `use_ai=true`: send only the compact, sanitized trace summary to the optional AI
  investigator. `OPENAI_API_KEY` is needed only for this choice.

The parser inventories resources but does not extract them, inspect screenshots, or
send binary files, raw bodies, cookies, authorization headers, or the archive to AI.
URL query parameters commonly used for tokens and credentials are redacted. Archive
file count, entry size, aggregate size, upload size, path safety, file type, and
compression ratio are validated before content is read.

> **Privacy warning:** Playwright traces can contain sensitive application
> information. Only upload traces that you are authorized to analyze.

### Trace examples

Generate the synthetic ZIP examples locally first. The generated archives are
ignored by Git so code-review systems do not need to accept binary patches:

```bash
python sample_data/traces/generate_samples.py
```

```bash
curl -F trace_file=@sample_data/traces/locator_timeout.zip \
  'http://127.0.0.1:8000/analyze-trace?use_ai=false'

curl -F trace_file=@sample_data/traces/network_503.zip \
  -F junit_file=@sample_data/junit.xml \
  'http://127.0.0.1:8000/analyze-trace?use_ai=true'
```
