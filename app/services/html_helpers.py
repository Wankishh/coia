"""HTML extraction and persistence helpers."""

import re
from pathlib import Path
from typing import Optional

HTML_BLOCK_RE = re.compile(
    r"```(?:html)?\s*(<!DOCTYPE html[\s\S]*?</html>|<html[\s\S]*?</html>)\s*```",
    re.IGNORECASE,
)
HTML_DOC_RE = re.compile(
    r"(<!DOCTYPE html[\s\S]*?</html>|<html[\s\S]*?</html>)",
    re.IGNORECASE,
)


def extract_html_from_text(text: str) -> Optional[str]:
    """Extract a full HTML document from model output if present."""
    if not text:
        return None

    fenced = HTML_BLOCK_RE.search(text)
    if fenced:
        return fenced.group(1).strip()

    bare = HTML_DOC_RE.search(text)
    if bare:
        return bare.group(1).strip()

    return None


def persist_html_report(workspace: Path, html: str, filename: str = "report.html") -> Path:
    """Write HTML into an agent workspace and return the absolute path."""
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / filename
    path.write_text(html, encoding="utf-8")
    return path
