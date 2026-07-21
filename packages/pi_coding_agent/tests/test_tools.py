"""Seam: built-in coding tools against temporary directories + fake StreamFn Agent."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pi_agent.types import AssistantStreamDone, AssistantStreamEvent, AssistantStreamStart
from pi_coding_agent.tools import create_builtin_tools

from pi_agent import (
    Agent,
    AgentToolResult,
    AssistantMessage,
    StreamRequest,
    ToolCall,
    ToolResultMessage,
)


def _scripted_stream(responses: list[AssistantMessage]):
    remaining = list(responses)

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        msg = remaining.pop(0)
        yield AssistantStreamStart(partial=AssistantMessage(content=""))
        yield AssistantStreamDone(message=msg)

    return stream_fn


async def test_read_supports_line_window_and_truncation(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("\n".join(f"line-{i}" for i in range(1, 21)), encoding="utf-8")
    tools = {t.name: t for t in create_builtin_tools(cwd=tmp_path)}
    read = tools["read"]
    assert read.execute is not None

    windowed = await read.execute(
        "1",
        {"path": "notes.txt", "offset": 5, "limit": 3},
    )
    assert "line-5" in windowed.content
    assert "line-7" in windowed.content
    assert "line-4" not in windowed.content
    assert "line-8" not in windowed.content

    huge = tmp_path / "huge.txt"
    huge.write_text("\n".join(f"L{i}" * 40 for i in range(2500)), encoding="utf-8")
    truncated = await read.execute("2", {"path": "huge.txt"})
    assert "Truncated" in truncated.content or "Showing lines" in truncated.content
    assert "Traceback" not in truncated.content


async def test_write_creates_and_overwrites_whole_file(tmp_path: Path) -> None:
    tools = {t.name: t for t in create_builtin_tools(cwd=tmp_path)}
    write = tools["write"]
    assert write.execute is not None

    nested = "subdir/a.txt"
    result = await write.execute("1", {"path": nested, "content": "hello"})
    assert "Successfully wrote" in result.content
    assert (tmp_path / nested).read_text(encoding="utf-8") == "hello"

    await write.execute("2", {"path": nested, "content": "world"})
    assert (tmp_path / nested).read_text(encoding="utf-8") == "world"


async def test_edit_multi_replace_all_or_nothing_and_replace_all(tmp_path: Path) -> None:
    path = tmp_path / "code.py"
    path.write_text("alpha\nbeta\nalpha\ngamma\n", encoding="utf-8")
    tools = {t.name: t for t in create_builtin_tools(cwd=tmp_path)}
    edit = tools["edit"]
    assert edit.execute is not None

    with pytest.raises(Exception, match="occurrences|unique"):
        await edit.execute(
            "1",
            {
                "path": "code.py",
                "edits": [{"oldText": "alpha", "newText": "ALPHA"}],
            },
        )
    assert path.read_text(encoding="utf-8") == "alpha\nbeta\nalpha\ngamma\n"

    ok = await edit.execute(
        "2",
        {
            "path": "code.py",
            "edits": [
                {"oldText": "alpha", "newText": "ALPHA", "replace_all": True},
                {"oldText": "beta", "newText": "BETA"},
            ],
        },
    )
    assert "Successfully replaced" in ok.content
    assert path.read_text(encoding="utf-8") == "ALPHA\nBETA\nALPHA\ngamma\n"

    with pytest.raises(Exception, match="overlap|Could not find"):
        await edit.execute(
            "3",
            {
                "path": "code.py",
                "edits": [
                    {"oldText": "ALPHA\nBETA", "newText": "X"},
                    {"oldText": "BETA\nALPHA", "newText": "Y"},
                ],
            },
        )


async def test_edit_and_write_share_per_realpath_queue(tmp_path: Path) -> None:
    from pi_coding_agent.tools.file_mutation_queue import with_file_mutation_queue

    target = tmp_path / "shared.txt"
    target.write_text("v0\n", encoding="utf-8")
    tools = {t.name: t for t in create_builtin_tools(cwd=tmp_path)}
    edit = tools["edit"]
    assert edit.execute is not None

    order: list[str] = []
    release_write = asyncio.Event()
    write_started = asyncio.Event()

    async def run_write() -> None:
        async def mutate() -> AgentToolResult:
            write_started.set()
            order.append("write-enter")
            await release_write.wait()
            target.write_text("from-write\n", encoding="utf-8")
            order.append("write-exit")
            return AgentToolResult(content="wrote")

        await with_file_mutation_queue(target, mutate)

    async def run_edit() -> None:
        await write_started.wait()
        order.append("edit-schedule")
        execute = edit.execute
        assert execute is not None
        await execute(
            "e",
            {
                "path": "shared.txt",
                "edits": [{"oldText": "from-write\n", "newText": "from-edit\n"}],
            },
        )
        order.append("edit-done")

    write_task = asyncio.create_task(run_write())
    edit_task = asyncio.create_task(run_edit())
    await write_started.wait()
    await asyncio.sleep(0.02)
    assert target.read_text(encoding="utf-8") == "v0\n"
    release_write.set()
    await asyncio.gather(write_task, edit_task)

    assert order == ["write-enter", "edit-schedule", "write-exit", "edit-done"]
    assert target.read_text(encoding="utf-8") == "from-edit\n"


async def test_edit_description_mentions_soft_read_guidance() -> None:
    tools = {t.name: t for t in create_builtin_tools(cwd=Path("."))}
    text = (tools["edit"].description or "").lower()
    assert "read" in text


async def test_bash_uses_cwd_timeout_and_truncates(tmp_path: Path) -> None:
    tools = {t.name: t for t in create_builtin_tools(cwd=tmp_path)}
    bash = tools["bash"]
    assert bash.execute is not None

    (tmp_path / "marker.txt").write_text("ok", encoding="utf-8")
    listed = await bash.execute("1", {"command": "ls"})
    assert "marker.txt" in listed.content

    with pytest.raises(Exception, match="timed out|timeout"):
        await bash.execute("2", {"command": "sleep 2", "timeout": 0.2})

    long_cmd = "python -c \"print('x'*80*3000)\""
    truncated = await bash.execute("3", {"command": long_cmd})
    assert "Truncated" in truncated.content or "Showing" in truncated.content


async def test_tool_failures_are_actionable_without_traceback(tmp_path: Path) -> None:
    tools = {t.name: t for t in create_builtin_tools(cwd=tmp_path)}
    read = tools["read"]
    assert read.execute is not None
    with pytest.raises(Exception) as excinfo:
        await read.execute("1", {"path": "missing.txt"})
    msg = str(excinfo.value)
    assert "missing.txt" in msg or "No such file" in msg or "not found" in msg.lower()
    assert "Traceback" not in msg


async def test_fake_stream_agent_turn_exercises_read_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hello agent\n", encoding="utf-8")
    tools = create_builtin_tools(cwd=tmp_path)
    agent = Agent(
        stream_fn=_scripted_stream(
            [
                AssistantMessage(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="read",
                            arguments={"path": "hello.txt"},
                        )
                    ],
                    stop_reason="toolUse",
                ),
                AssistantMessage(content="done", stop_reason="stop"),
            ]
        ),
        tools=tools,
        tool_execution="sequential",
    )
    await agent.prompt("read the file")
    results = [m for m in agent.messages if isinstance(m, ToolResultMessage)]
    assert results
    assert results[0].is_error is False
    assert "hello agent" in results[0].content
