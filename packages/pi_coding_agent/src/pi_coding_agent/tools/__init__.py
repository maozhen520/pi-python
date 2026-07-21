"""Built-in coding tools registered on Agent."""

from __future__ import annotations

from pathlib import Path

from pi_agent import AgentTool
from pi_coding_agent.tools.bash import create_bash_tool
from pi_coding_agent.tools.edit import create_edit_tool
from pi_coding_agent.tools.read import create_read_tool
from pi_coding_agent.tools.write import create_write_tool


def create_builtin_tools(*, cwd: Path | str | None = None) -> list[AgentTool]:
    root = Path.cwd() if cwd is None else Path(cwd)
    root = root.resolve()
    return [
        create_read_tool(root),
        create_write_tool(root),
        create_edit_tool(root),
        create_bash_tool(root),
    ]


__all__ = ["create_builtin_tools"]
