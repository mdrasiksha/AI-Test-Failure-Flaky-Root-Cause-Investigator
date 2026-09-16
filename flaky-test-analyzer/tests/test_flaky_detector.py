from backend.flaky_detector import analyze_history, get_test_id


def make_test_result(
    status: str, name: str = "example", classname: str | None = "tests.sample"
) -> dict[str, object]:
    return {"test_name": name, "classname": classname, "status": status}


def analyze(*statuses: str) -> dict[str, object]:
    return analyze_history([[make_test_result(status)] for status in statuses])[0]


def test_all_passes_are_stable() -> None:
    assert analyze("passed", "passed", "passed")["flaky_status"] == "stable"


def test_all_failures_are_consistently_failing() -> None:
    assert (
        analyze("failed", "failed", "failed")["flaky_status"] == "consistently_failing"
    )


def test_short_mixed_history_is_possible() -> None:
    assert analyze("passed", "failed", "passed")["flaky_status"] == "possible"


def test_long_alternating_history_is_high() -> None:
    result = analyze("passed", "passed", "failed", "passed", "failed", "passed")
    assert result["flaky_status"] == "high"
    assert result["status_transitions"] == 4


def test_two_runs_are_insufficient() -> None:
    assert analyze("passed", "failed")["flaky_status"] == "insufficient_history"


def test_skipped_status_is_ignored_for_execution_calculations() -> None:
    result = analyze("passed", "skipped", "passed")
    assert result["flaky_status"] == "stable"
    assert result["executed_runs"] == 2
    assert result["skipped_runs"] == 1


def test_errors_contribute_to_high_flakiness() -> None:
    result = analyze("passed", "error", "passed", "error", "passed")
    assert result["flaky_status"] == "high"
    assert result["error_runs"] == 2


def test_multiple_tests_are_aggregated_independently() -> None:
    runs = [
        [make_test_result("passed", "one"), make_test_result("failed", "two")],
        [make_test_result("passed", "one"), make_test_result("failed", "two")],
        [make_test_result("passed", "one"), make_test_result("failed", "two")],
    ]
    results = analyze_history(runs)
    assert [result["test_id"] for result in results] == [
        "tests.sample::one",
        "tests.sample::two",
    ]
    assert [result["flaky_status"] for result in results] == [
        "stable",
        "consistently_failing",
    ]


def test_missing_classname_uses_test_name() -> None:
    assert get_test_id(make_test_result("passed", classname=None)) == "example"


def test_test_appearing_only_in_some_runs_counts_appearances() -> None:
    result = analyze_history(
        [
            [make_test_result("passed")],
            [],
            [make_test_result("failed")],
            [make_test_result("passed")],
        ]
    )[0]
    assert result["total_runs"] == 3
    assert result["executed_runs"] == 3
    assert result["flaky_status"] == "possible"


def test_failure_rate_is_rounded_to_two_decimal_places() -> None:
    assert analyze("passed", "passed", "failed")["failure_rate"] == 33.33


def test_skips_do_not_create_status_transitions() -> None:
    result = analyze("passed", "skipped", "failed", "skipped", "passed")
    assert result["status_transitions"] == 2
