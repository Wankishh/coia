"""Extract visible model text and detect CoT / scratchpad dumps."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

__all__ = [
    "EMPTY_RUN_DELIVERABLE_ERROR",
    "message_content_to_str",
    "content_block_type_labels",
    "has_usable_run_deliverable",
    "looks_like_scratchpad",
    "truncate_for_chat",
]

# Structured content block types that must never become user-visible text.
_SKIP_BLOCK_TYPES = frozenset(
    {
        "thinking",
        "reasoning",
        "redacted_thinking",
    }
)

# Provider block types that carry visible answer text (OpenAI Responses / OpenRouter).
_TEXT_BLOCK_TYPES = frozenset(
    {
        "text",
        "output_text",
        "input_text",
    }
)

EMPTY_RUN_DELIVERABLE_ERROR = (
    "Run finished without an HTML report or final summary"
)

# Planning / narration openers typical of incomplete agent scratchpads.
_NARRATION_RE = re.compile(
    r"(?is)^\s*("
    r"let me\b|let's\b|lets\b|now i\b|now also\b|now we\b|"
    r"i will\b|i'll\b|i am going to\b|i'm going to\b|"
    r"going to\b|next i\b|okay[,.]?\s*i\b|ok[,.]?\s*i\b|"
    r"let's compute\b|lets compute\b|now computing\b|"
    r"step\s+\d+|first[,.]?\s+i\b|i need to\b|i should\b"
    r")"
)

_REPORT_STRUCTURE_RE = re.compile(
    r"(?m)^(?:#{1,6}\s+\S|(?:[-*]|\d+\.)\s+\S)"
)

# Length / repetition thresholds for Agent-runs chat hygiene.
_EXTREME_LEN = 8_000
_HARD_LEN = 24_000
_REPETITION_MIN_LINES = 25
_REPETITION_RATIO = 0.35
_SHORT_NARRATION_MAX = 600
_MEDIUM_NARRATION_MAX = 2_500


def _block_type(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("type") or "").strip().lower()
    return str(getattr(block, "type", "") or "").strip().lower()


def _extract_visible_block_text(block: Any) -> str:
    """
    Pull user-visible text from one content block.

    Never returns thinking / reasoning payloads. Unknown block shapes are
    omitted rather than stringified (avoids repr / CoT dumps).
    """
    block_type = _block_type(block)
    if block_type in _SKIP_BLOCK_TYPES:
        return ""

    if isinstance(block, str):
        return block

    if isinstance(block, dict):
        text = block.get("text")
        if isinstance(text, str) and text:
            return text
        # Responses API / some OpenRouter adapters put answer text here.
        if block_type in _TEXT_BLOCK_TYPES:
            for key in ("content", "value", "output_text"):
                val = block.get(key)
                if isinstance(val, str) and val.strip():
                    return val
        # Bare content string on an untyped / text-like block (not tool_use, etc.).
        if block_type in ("", *_TEXT_BLOCK_TYPES):
            content = block.get("content")
            if isinstance(content, str) and content.strip():
                return content
        return ""

    text_attr = getattr(block, "text", None)
    if isinstance(text_attr, str) and text_attr:
        return text_attr
    if block_type in _TEXT_BLOCK_TYPES:
        content_attr = getattr(block, "content", None)
        if isinstance(content_attr, str) and content_attr.strip():
            return content_attr
    return ""


def content_block_type_labels(content: Any) -> list[str]:
    """Return block type labels for debug logging (no payload text)."""
    if content is None:
        return ["none"]
    if isinstance(content, str):
        return ["str"] if content else ["str:empty"]
    if not isinstance(content, list):
        return [type(content).__name__]
    labels: list[str] = []
    for block in content:
        if isinstance(block, str):
            labels.append("str" if block else "str:empty")
            continue
        block_type = _block_type(block)
        labels.append(block_type or type(block).__name__)
    return labels or ["list:empty"]


def message_content_to_str(content: Any) -> str:
    """
    Flatten LangChain / provider message content to plain text.

    Skips structured thinking / reasoning blocks so they never become chat copy.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            piece = _extract_visible_block_text(block)
            if piece:
                parts.append(piece)
        return "\n".join(parts)
    return str(content)


def has_usable_run_deliverable(
    output_text: str,
    output_html: Optional[str],
    *,
    html_tool_expected: bool,
) -> bool:
    """
    True when a cron/manual run produced something presentable.

    HTML alone counts. Clean non-scratchpad text counts. Scratchpad-only
    text is not enough when the HTML report tool was expected.
    """
    if (output_html or "").strip():
        return True
    body = (output_text or "").strip()
    if not body:
        return False
    if looks_like_scratchpad(body):
        return not html_tool_expected
    return True


def truncate_for_chat(text: str, max_len: int) -> str:
    cleaned = (text or "").strip()
    if max_len <= 0 or len(cleaned) <= max_len:
        return cleaned
    if max_len <= 1:
        return "…"
    return cleaned[: max_len - 1].rstrip() + "…"


def looks_like_scratchpad(text: str) -> bool:
    """
    Heuristic: model chain-of-thought / tool narration unsuitable as a run report.

    Tuned to catch extreme-length dumps, heavy line repetition, and incomplete
    "Let me…" / "Now I will…" narration without a real report structure.
    """
    body = (text or "").strip()
    if not body:
        return False

    has_structure = bool(_REPORT_STRUCTURE_RE.search(body))
    n = len(body)

    if n >= _HARD_LEN:
        return True
    if n >= _EXTREME_LEN and not has_structure:
        return True

    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) >= _REPETITION_MIN_LINES:
        top_line_count = Counter(lines).most_common(1)[0][1]
        if top_line_count / len(lines) >= _REPETITION_RATIO:
            return True
        prefixes = Counter(ln[:48] for ln in lines)
        top_prefix_count = prefixes.most_common(1)[0][1]
        if top_prefix_count / len(lines) >= _REPETITION_RATIO:
            return True

    if has_structure:
        return False

    if n <= _SHORT_NARRATION_MAX and _NARRATION_RE.match(body):
        return True

    if n <= _MEDIUM_NARRATION_MAX and _NARRATION_RE.match(body):
        # Medium narration without report structure is almost never a deliverable.
        return True

    return False
