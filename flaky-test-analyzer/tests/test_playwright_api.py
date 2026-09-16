from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_upload_includes_framework_analysis() -> None:
    path = Path("sample_data/playwright/locator_timeout.xml")
    with path.open("rb") as report:
        response = client.post("/upload-junit", files={"file": (path.name, report, "application/xml")})
    assert response.status_code == 200
    test = response.json()["tests"][0]
    assert test["classification"] is not None
    assert test["framework_analysis"]["issue_type"] == "locator_not_found"


def test_non_playwright_failure_has_null_framework_analysis() -> None:
    response = client.post(
        "/upload-junit",
        files={"file": ("generic.xml", '<testsuite><testcase name="x"><failure type="AssertionError">no</failure></testcase></testsuite>', "application/xml")},
    )
    assert response.json()["tests"][0]["framework_analysis"] is None


def test_history_uses_latest_failure_not_latest_pass() -> None:
    failed = '<testsuite><testcase classname="tests.ui" name="pay"><failure type="TimeoutError">locator.click: element is not visible</failure></testcase></testsuite>'
    passed = '<testsuite><testcase classname="tests.ui" name="pay"/></testsuite>'
    response = client.post(
        "/analyze-history",
        files=[("files", ("one.xml", failed, "application/xml")), ("files", ("two.xml", passed, "application/xml")), ("files", ("three.xml", passed, "application/xml"))],
    )
    analysis = response.json()["tests"][0]["latest_failure_analysis"]
    assert analysis["issue_type"] == "element_not_visible"
