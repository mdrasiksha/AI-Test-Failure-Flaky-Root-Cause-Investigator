from backend.sanitizer import sanitize_text


def test_redacts_bearer_token() -> None:
    assert (
        sanitize_text("Authorization: Bearer abc123")
        == "Authorization: Bearer [REDACTED]"
    )


def test_redacts_password() -> None:
    assert sanitize_text("password=hunter2") == "password=[REDACTED]"


def test_redacts_api_key_pattern() -> None:
    assert sanitize_text("OPENAI_API_KEY=not-a-real-key") == "OPENAI_API_KEY=[REDACTED]"


def test_normal_error_text_is_unchanged() -> None:
    text = "TimeoutError: locator.click exceeded 5000ms"
    assert sanitize_text(text) == text


def test_long_trace_is_trimmed_and_repeated_lines_removed() -> None:
    result = sanitize_text("same\nsame\n" + "x" * 100, max_chars=40)
    assert result.startswith("same\n")
    assert result.endswith("...[TRUNCATED]")
    assert len(result) == 40
