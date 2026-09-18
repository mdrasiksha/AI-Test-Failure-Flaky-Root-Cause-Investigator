"""Step 9A production, limits, headers, and upload-lifecycle coverage."""

import asyncio
from io import BytesIO
import os
from pathlib import Path
import re
import subprocess
import sys

from fastapi import UploadFile
from fastapi.testclient import TestClient
import pytest

import backend.main as main

client = TestClient(main.app)


def test_health_is_secret_free_and_security_headers_are_present():
    response = client.get("/health")
    assert response.json() == {"status": "ok", "service": "flaky-test-analyzer"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert "OPENAI" not in response.text


def test_application_imports_without_openai_api_key():
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", "from backend.main import app; print(app.title)"],
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == "Flaky Test Analyzer API"


def test_application_imports_when_analytics_storage_is_unavailable():
    environment = os.environ.copy()
    environment.update(
        {
            "ANALYTICS_ENABLED": "true",
            "ANALYTICS_DB_PATH": "/dev/null/analytics.db",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "from backend.main import app; print(app.title)"],
        env=environment,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Flaky Test Analyzer API"


def test_render_deployment_configuration():
    app_root = Path(__file__).resolve().parents[1]
    repository_root = app_root.parent

    assert (app_root / ".python-version").read_text() == "3.12.9\n"
    blueprint = (repository_root / "render.yaml").read_text()
    expected_settings = (
        "type: web",
        "runtime: python",
        "rootDir: flaky-test-analyzer",
        "buildCommand: pip install -r requirements.txt",
        "startCommand: uvicorn backend.main:app --host 0.0.0.0 --port $PORT",
        "healthCheckPath: /health",
    )
    assert all(setting in blueprint for setting in expected_settings)
    assert "OPENAI_API_KEY" not in blueprint
    assert "ADMIN_METRICS_TOKEN" not in blueprint


def test_requirements_include_web_runtime_dependencies():
    root = Path(__file__).resolve().parents[1]
    requirements = {
        re.split(r"[<>=!~]", line, maxsplit=1)[0].lower()
        for line in (root / "requirements.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }
    assert {
        "fastapi",
        "uvicorn",
        "python-multipart",
        "pydantic",
        "starlette",
        "openai",
        "python-dotenv",
        "jinja2",
    } <= requirements


def test_production_entry_point_binds_all_interfaces_and_configured_port(monkeypatch):
    import backend.production as production

    seen = {}
    monkeypatch.setattr(production, "PORT", 9123)
    monkeypatch.setattr(production.uvicorn, "run", lambda *args, **kwargs: seen.update(args=args, **kwargs))
    production.main()
    assert seen == {"args": ("backend.main:app",), "host": "0.0.0.0", "port": 9123}


def test_junit_upload_limit_returns_413(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_MB", 1)
    response = client.post(
        "/upload-junit",
        files={"file": ("large.xml", b"x" * (1024 * 1024 + 1), "application/xml")},
    )
    assert response.status_code == 413
    assert "configured 1 MB" in response.json()["detail"]


def test_ai_limit_keeps_deterministic_results(monkeypatch):
    monkeypatch.setenv("MAX_AI_TESTS_PER_REQUEST", "2")
    calls = []
    monkeypatch.setattr(main, "analyze_with_ai", lambda evidence: calls.append(evidence) or {"summary": "ok"})
    cases = "".join(
        f'<testcase name="failure-{number}"><failure type="AssertionError">bad</failure></testcase>'
        for number in range(4)
    )
    response = client.post(
        "/analyze-ai",
        files={"file": ("report.xml", f"<testsuite>{cases}</testsuite>", "application/xml")},
    )
    body = response.json()
    assert response.status_code == 200
    assert len(calls) == body["failures_analyzed"] == body["ai_limit"] == 2
    assert body["total_failures"] == len(body["tests"]) == 4
    assert body["ai_analysis_limited"] is True
    assert "deterministic analysis is included" in body["ai_limit_message"]
    assert all(item["classification"] for item in body["tests"])
    assert [item["ai_analysis"] is not None for item in body["tests"]] == [True, True, False, False]


@pytest.mark.parametrize("valid", [True, False])
def test_upload_is_closed_after_success_and_failure(valid):
    content = b'<testsuite><testcase name="ok"/></testsuite>' if valid else b"<broken"
    upload = UploadFile(BytesIO(content), filename="report.xml")

    async def invoke():
        if valid:
            await main.upload_junit(upload)
        else:
            with pytest.raises(main.HTTPException):
                await main.upload_junit(upload)

    asyncio.run(invoke())
    assert upload.file.closed


def test_env_and_docker_context_exclude_secrets():
    root = Path(__file__).resolve().parents[1]
    assert ".env" in (root / ".gitignore").read_text().splitlines()
    ignored = (root / ".dockerignore").read_text().splitlines()
    assert ".env" in ignored and ".env.*" in ignored
    assert "OPENAI_API_KEY=" not in (root / "Dockerfile").read_text()
