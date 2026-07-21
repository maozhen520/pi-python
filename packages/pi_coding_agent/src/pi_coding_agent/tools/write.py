"""Built-in `write` tool: whole-file create/overwrite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pi_agent import AgentTool, AgentToolResult
from pi_coding_agent.tools.file_mutation_queue import with_file_mutation_queue
from pi_coding_agent.tools.path_utils import resolve_to_cwd

WRITE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the file to write (relative or absolute)",
        },
        "content": {"type": "string", "description": "Content to write to the file"},
    },
    "required": ["path", "content"],
}


def create_write_tool(cwd: Path) -> AgentTool:
    async def execute(_tool_call_id: str, args: dict[str, Any], **_kwargs: Any) -> AgentToolResult:
        path = str(args["path"])
        content = str(args["content"])
        absolute = resolve_to_cwd(path, cwd)

        async def mutate() -> AgentToolResult:
            try:
                absolute.parent.mkdir(parents=True, exist_ok=True)
                absolute.write_text(content, encoding="utf-8")
            except OSError as exc:
                raise OSError(f"Could not write file: {path}. {exc.strerror or exc}") from None
            return AgentToolResult(
                content=f"Successfully wrote {len(content.encode('utf-8'))} bytes to {path}"
            )

        return await with_file_mutation_queue(absolute, mutate)

    return AgentTool(
        name="write",
        label="write",
        description=(
            "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. "
            "Automatically creates parent directories."
        ),
        parameters=WRITE_PARAMETERS,
        execute=execute,
    )
