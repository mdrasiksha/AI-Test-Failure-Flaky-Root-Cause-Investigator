import pytest

from backend.parser import JUnitParseError, parse_junit_xml


def parse_testcase(body: str = "", attributes: str = "") -> dict[str, object]:
    return parse_junit_xml(
        f'<testsuite><testcase name="example" time="1.25" {attributes}>{body}</testcase></testsuite>'
    )[0]


def test_passing_testcase() -> None:
    result = parse_testcase(attributes='classname="tests.test_example"')
    assert result == {
        "test_name": "example",
        "classname": "tests.test_example",
        "duration": 1.25,
        "status": "passed",
        "error_type": None,
        "error_message": None,
        "stack_trace": None,
    }


def test_failed_testcase() -> None:
    result = parse_testcase(
        '<failure type="AssertionError" message="expected true">assert false</failure>'
    )
    assert result["status"] == "failed"
    assert result["error_type"] == "AssertionError"
    assert result["error_message"] == "expected true"
    assert result["stack_trace"] == "assert false"


def test_error_testcase() -> None:
    result = parse_testcase('<error type="TimeoutError" message="timed out">trace</error>')
    assert result["status"] == "error"
    assert result["error_type"] == "TimeoutError"


def test_skipped_testcase() -> None:
    result = parse_testcase('<skipped message="not supported"/>')
    assert result["status"] == "skipped"
    assert result["error_message"] is None


def test_multiple_testcases() -> None:
    results = parse_junit_xml(
        '<testsuite><testcase name="one"/><testcase name="two"><failure/></testcase></testsuite>'
    )
    assert [result["test_name"] for result in results] == ["one", "two"]
    assert [result["status"] for result in results] == ["passed", "failed"]


def test_missing_classname() -> None:
    assert parse_testcase()["classname"] is None


def test_missing_duration() -> None:
    result = parse_junit_xml('<testsuite><testcase name="example"/></testsuite>')[0]
    assert result["duration"] is None


def test_malformed_xml() -> None:
    with pytest.raises(JUnitParseError, match="Malformed JUnit XML"):
        parse_junit_xml("<testsuite><testcase></testsuite>")


def test_testsuites_with_multiple_suites() -> None:
    results = parse_junit_xml(
        """<testsuites>
        <testsuite name="first"><testcase name="one"/></testsuite>
        <testsuite name="second"><testcase name="two"><error/></testcase></testsuite>
        </testsuites>"""
    )
    assert len(results) == 2
    assert [result["status"] for result in results] == ["passed", "error"]


def test_invalid_duration_has_clear_error() -> None:
    with pytest.raises(JUnitParseError, match="Invalid testcase duration"):
        parse_junit_xml('<testsuite><testcase time="slow"/></testsuite>')
