"""Seam: stateful Agent — subscribe settlement, prompt/continue/steer/follow_up."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from pi_agent.types import (
    AssistantStreamDone,
    AssistantStreamEvent,
    AssistantStreamStart,
)

from pi_agent import (
    Agent,
    AgentEndEvent,
    AgentEvent,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    MessageEndEvent,
    StreamRequest,
    ToolCall,
    ToolExecutionStartEvent,
    UserMessage,
)


def _scripted_stream(
    responses: list[AssistantMessage],
):
    remaining = list(responses)

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        msg = remaining.pop(0)
        yield AssistantStreamStart(partial=AssistantMessage(content=""))
        yield AssistantStreamDone(message=msg)

    return stream_fn


async def test_subscribe_awaits_handlers_before_runtime_advances() -> None:
    order: list[str] = []
    gate = asyncio.Event()

    async def execute(*_a, **_k) -> AgentToolResult:
        return await _async_result(order, "exec")

    agent = Agent(
        stream_fn=_scripted_stream(
            [
                AssistantMessage(
                    content=None,
                    tool_calls=[ToolCall(id="1", name="t", arguments={})],
                    stop_reason="toolUse",
                ),
                AssistantMessage(content="done", stop_reason="stop"),
            ]
        ),
        tools=[AgentTool(name="t", execute=execute)],
        tool_execution="sequential",
    )

    async def on_event(event: AgentEvent) -> None:
        if isinstance(event, MessageEndEvent) and event.message.role == "assistant":
            order.append("assistant_end_handler_start")
            await gate.wait()
            order.append("assistant_end_handler_done")
            assert agent.messages[-1].role == "assistant"

    agent.subscribe(on_event)

    async def release() -> None:
        await asyncio.sleep(0.01)
        assert "exec" not in order
        gate.set()

    releaser = asyncio.create_task(release())
    await agent.prompt("go")
    await releaser

    assert order[:3] == [
        "assistant_end_handler_start",
        "assistant_end_handler_done",
        "exec",
    ]
    assert agent.messages[-1].content == "done"


async def _async_result(order: list[str], label: str) -> AgentToolResult:
    order.append(label)
    return AgentToolResult(content=label)


async def test_prompt_rejects_concurrent_prompt() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_stream(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        started.set()
        await release.wait()
        yield AssistantStreamStart(partial=AssistantMessage(content=""))
        yield AssistantStreamDone(message=AssistantMessage(content="ok", stop_reason="stop"))

    agent = Agent(stream_fn=slow_stream)
    task = asyncio.create_task(agent.prompt("one"))
    await started.wait()
    with pytest.raises(RuntimeError, match="already processing"):
        await agent.prompt("two")
    release.set()
    await task


async def test_steer_injects_after_turn_tools() -> None:
    responses = [
        AssistantMessage(
            content=None,
            tool_calls=[ToolCall(id="1", name="t", arguments={})],
            stop_reason="toolUse",
        ),
        AssistantMessage(content="after-steer", stop_reason="stop"),
    ]

    async def execute(_id: str, _args: dict, **_k) -> AgentToolResult:
        return AgentToolResult(content="tool-ok")

    agent = Agent(
        stream_fn=_scripted_stream(responses),
        tools=[AgentTool(name="t", execute=execute)],
        tool_execution="sequential",
    )

    async def on_event(event: AgentEvent) -> None:
        if isinstance(event, ToolExecutionStartEvent):
            agent.steer(UserMessage(content="steer now"))

    agent.subscribe(on_event)
    await agent.prompt("go")

    contents = [getattr(m, "content", None) for m in agent.messages]
    assert "steer now" in contents
    assert contents[-1] == "after-steer"


async def test_follow_up_runs_after_agent_would_stop() -> None:
    responses = [
        AssistantMessage(content="first", stop_reason="stop"),
        AssistantMessage(content="follow", stop_reason="stop"),
    ]
    agent = Agent(stream_fn=_scripted_stream(responses))

    async def on_event(event: AgentEvent) -> None:
        if (
            isinstance(event, MessageEndEvent)
            and getattr(event.message, "content", None) == "first"
        ):
            agent.follow_up(UserMessage(content="more"))

    agent.subscribe(on_event)
    await agent.prompt("go")
    assert [getattr(m, "content", None) for m in agent.messages] == [
        "go",
        "first",
        "more",
        "follow",
    ]


async def test_continue_resumes_without_new_prompt() -> None:
    agent = Agent(
        stream_fn=_scripted_stream([AssistantMessage(content="continued", stop_reason="stop")]),
        messages=[UserMessage(content="already there")],
    )
    await agent.continue_()
    assert [getattr(m, "content", None) for m in agent.messages] == [
        "already there",
        "continued",
    ]


async def test_await_prompt_waits_for_agent_end_listeners() -> None:
    order: list[str] = []
    gate = asyncio.Event()

    agent = Agent(
        stream_fn=_scripted_stream([AssistantMessage(content="x", stop_reason="stop")]),
    )

    async def on_event(event: AgentEvent) -> None:
        if isinstance(event, AgentEndEvent):
            order.append("end_start")
            await gate.wait()
            order.append("end_done")

    agent.subscribe(on_event)

    async def release() -> None:
        await asyncio.sleep(0.01)
        assert "end_done" not in order
        gate.set()

    releaser = asyncio.create_task(release())
    await agent.prompt("hi")
    await releaser
    assert order == ["end_start", "end_done"]
    assert agent.is_streaming is False
