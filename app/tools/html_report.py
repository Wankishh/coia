"""Tool for writing HTML reports into the agent workspace."""

from pathlib import Path
from typing import Callable, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services.html_helpers import persist_html_report


class WriteHtmlReportInput(BaseModel):
    html: str = Field(description="Full HTML document content to save as the report")
    filename: str = Field(
        default="report.html",
        description="Filename within the agent workspace (default report.html)",
    )


def create_write_html_report_tool(
    workspace: Path,
    on_html: Optional[Callable[[str], None]] = None,
) -> StructuredTool:
    workspace.mkdir(parents=True, exist_ok=True)

    def write_html_report(html: str, filename: str = "report.html") -> str:
        # Keep filename workspace-relative and simple
        safe_name = Path(filename).name or "report.html"
        if not safe_name.lower().endswith(".html"):
            safe_name = f"{safe_name}.html"
        path = persist_html_report(workspace, html, filename=safe_name)
        if on_html is not None:
            on_html(html)
        return (
            f"HTML report written to {safe_name} "
            f"({len(html)} characters). Absolute path: {path}"
        )

    return StructuredTool.from_function(
        func=write_html_report,
        name="write_html_report",
        description=(
            "Write a complete HTML report into the agent workspace and return "
            "confirmation. Prefer this tool when producing visual/analytical reports "
            "so the HTML is captured on the execution log."
        ),
        args_schema=WriteHtmlReportInput,
    )
