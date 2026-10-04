"""Unit checks for Agent-runs chat formatting of execution results."""

from __future__ import annotations

from app.models.execution import ExecutionLog, ExecutionStatus, TriggerType
from app.services.chat_service import _format_run_result_content
from app.services.message_content import EMPTY_RUN_DELIVERABLE_ERROR


def test_format_empty_completed_run_is_clear() -> None:
    log = ExecutionLog(
        agent_id="a1",
        trigger_type=TriggerType.manual,
        status=ExecutionStatus.completed,
        output_text="",
        output_html=None,
    )
    text = _format_run_result_content(log)
    assert "No text or HTML deliverable was produced" in text
    assert "Executions" in text
    assert "(No text output.)" not in text


def test_format_failed_empty_deliverable_shows_error() -> None:
    log = ExecutionLog(
        agent_id="a1",
        trigger_type=TriggerType.cron,
        status=ExecutionStatus.failed,
        output_text="",
        output_html=None,
        error_message=EMPTY_RUN_DELIVERABLE_ERROR,
    )
    text = _format_run_result_content(log)
    assert f"Error: {EMPTY_RUN_DELIVERABLE_ERROR}" in text
    assert "Status: failed" in text


def test_format_html_run_uses_caption() -> None:
    log = ExecutionLog(
        agent_id="a1",
        trigger_type=TriggerType.manual,
        status=ExecutionStatus.completed,
        output_text="",
        output_html="<html><body><h1>Report</h1></body></html>",
    )
    text = _format_run_result_content(log)
    assert "HTML report attached." in text


def test_format_html_with_scratchpad_omits_cot() -> None:
    log = ExecutionLog(
        agent_id="a1",
        trigger_type=TriggerType.manual,
        status=ExecutionStatus.completed,
        output_text="Let me create the HTML report…",
        output_html="<html><body>ok</body></html>",
    )
    text = _format_run_result_content(log)
    assert "HTML report attached." in text
    assert "scratchpad omitted" in text
    assert "Let me create" not in text


if __name__ == "__main__":
    test_format_empty_completed_run_is_clear()
    test_format_failed_empty_deliverable_shows_error()
    test_format_html_run_uses_caption()
    test_format_html_with_scratchpad_omits_cot()
    print("ok")
