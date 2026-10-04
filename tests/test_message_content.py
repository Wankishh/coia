"""Unit checks for visible text extraction and scratchpad / CoT heuristics."""

from __future__ import annotations

from app.services.message_content import (
    content_block_type_labels,
    has_usable_run_deliverable,
    looks_like_scratchpad,
    message_content_to_str,
    truncate_for_chat,
)


def test_message_content_skips_thinking_blocks() -> None:
    content = [
        {"type": "thinking", "text": "secret chain of thought"},
        {"type": "reasoning", "thinking": "also secret"},
        {"type": "redacted_thinking", "data": "xxx"},
        {"type": "text", "text": "Visible answer"},
        " trailing plain",
    ]
    assert message_content_to_str(content) == "Visible answer\n trailing plain"


def test_message_content_extracts_output_text_blocks() -> None:
    content = [
        {"type": "thinking", "thinking": "hidden"},
        {"type": "output_text", "text": "Report ready"},
    ]
    assert message_content_to_str(content) == "Report ready"


def test_message_content_extracts_content_on_text_block() -> None:
    content = [{"type": "text", "content": "Via content key"}]
    assert message_content_to_str(content) == "Via content key"


def test_message_content_plain_string() -> None:
    assert message_content_to_str("hello") == "hello"
    assert message_content_to_str(None) == ""


def test_content_block_type_labels() -> None:
    assert content_block_type_labels(
        [
            {"type": "thinking", "text": "x"},
            {"type": "output_text", "text": "y"},
            "plain",
        ]
    ) == ["thinking", "output_text", "str"]


def test_has_usable_run_deliverable() -> None:
    assert (
        has_usable_run_deliverable("", None, html_tool_expected=True) is False
    )
    assert (
        has_usable_run_deliverable("", "<html></html>", html_tool_expected=True)
        is True
    )
    assert (
        has_usable_run_deliverable(
            "# Summary\n\n- ok", None, html_tool_expected=True
        )
        is True
    )
    assert (
        has_usable_run_deliverable(
            "Let me create the HTML report…",
            None,
            html_tool_expected=True,
        )
        is False
    )
    # Without HTML tool, scratchpad alone still counts as present text for status.
    assert (
        has_usable_run_deliverable(
            "Let me create the HTML report…",
            None,
            html_tool_expected=False,
        )
        is True
    )
    assert (
        has_usable_run_deliverable("", None, html_tool_expected=False) is False
    )


def test_looks_like_scratchpad_repetition() -> None:
    blob = "\n".join(["Now also row 12 looks interesting"] * 80)
    assert looks_like_scratchpad(blob) is True


def test_looks_like_scratchpad_incomplete_narration() -> None:
    assert looks_like_scratchpad("Let me create the HTML report…") is True
    assert looks_like_scratchpad("Now I will query the database and compute totals") is True


def test_clean_markdown_report_is_not_scratchpad() -> None:
    report = """# Weekly summary

## Highlights
- Revenue up 12%
- Churn flat

## Next steps
1. Review cohort retention
2. Ship pricing experiment
"""
    assert looks_like_scratchpad(report) is False


def test_extreme_length_without_structure() -> None:
    assert looks_like_scratchpad("x" * 9000) is True


def test_truncate_for_chat() -> None:
    assert truncate_for_chat("abcdef", 4) == "abc…"
    assert truncate_for_chat("short", 100) == "short"


if __name__ == "__main__":
    test_message_content_skips_thinking_blocks()
    test_message_content_extracts_output_text_blocks()
    test_message_content_extracts_content_on_text_block()
    test_message_content_plain_string()
    test_content_block_type_labels()
    test_has_usable_run_deliverable()
    test_looks_like_scratchpad_repetition()
    test_looks_like_scratchpad_incomplete_narration()
    test_clean_markdown_report_is_not_scratchpad()
    test_extreme_length_without_structure()
    test_truncate_for_chat()
    print("ok")
