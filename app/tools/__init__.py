"""Agent tools for Coia Agents.

Import submodules directly (e.g. ``app.tools.factory``, ``app.tools.sandbox_file``).
``build_tools_for_agent`` is available via lazy ``__getattr__`` for convenience.
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_tools_for_agent"]


def __getattr__(name: str) -> Any:
    if name == "build_tools_for_agent":
        from app.tools.factory import build_tools_for_agent

        return build_tools_for_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
