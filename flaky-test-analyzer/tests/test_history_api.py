from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_sample_history_endpoint() -> None:
    history = Path("sample_data/history")
    handles = [(history / f"run{number}.xml").open("rb") for number in range(1, 6)]
    try:
        response = client.post(
            "/analyze-history",
            files=[
                ("files", (handle.name, handle, "application/xml"))
                for handle in handles
            ],
        )
    finally:
        for handle in handles:
            handle.close()

    assert response.status_code == 200
    body = response.json()
    assert body["runs_analyzed"] == 5
    assert body["tests_analyzed"] == 3
    assert body["flaky_tests"] == 1
    assert {test["test_id"]: test["flaky_status"] for test in body["tests"]} == {
        "tests.test_shop::test_login": "stable",
        "tests.test_shop::test_payment": "high",
        "tests.test_shop::test_checkout": "consistently_failing",
    }


def test_history_error_names_malformed_file() -> None:
    response = client.post(
        "/analyze-history",
        files=[("files", ("broken.xml", "<testsuite>", "application/xml"))],
    )
    assert response.status_code == 400
    assert "broken.xml" in response.json()["detail"]


def test_history_rejects_empty_file() -> None:
    response = client.post(
        "/analyze-history", files=[("files", ("empty.xml", b"", "application/xml"))]
    )
    assert response.status_code == 400
    assert "empty.xml" in response.json()["detail"]


def test_history_rejects_report_without_testcases() -> None:
    response = client.post(
        "/analyze-history",
        files=[("files", ("none.xml", "<testsuite/>", "application/xml"))],
    )
    assert response.status_code == 400
    assert "no testcases" in response.json()["detail"]


def test_history_requires_files() -> None:
    response = client.post("/analyze-history")
    assert response.status_code == 400
