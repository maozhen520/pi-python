"""Seam: tool batching with before/after hooks under sequential|parallel modes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from pi_agent.types import (
    AssistantStreamDone,
    AssistantStreamEvent,
    AssistantStreamStart,
)

from pi_agent import (
    AfterToolCallContext,
    AfterToolCallResult,
    AgentContext,
    AgentEndEvent,
    AgentLoopConfig,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    BeforeToolCallContext,
    BeforeToolCallResult,
    MessageStartEvent,
    StreamRequest,
    ToolCall,
    ToolExecutionEndEvent,
    ToolResultMessage,
    TurnEndEvent,
    UserMessage,
    agent_loop,
    default_convert_to_llm,
)


async def test_sequential_tools_run_with_before_after_hooks() -> None:
    order: list[str] = []

    async def execute_echo(tool_call_id: str, args: dict, **_kwargs) -> AgentToolResult:
        order.append(f"exec:{args['name']}")
        return AgentToolResult(content=f"ok:{args['name']}")

    async def before(ctx: BeforeToolCallContext) -> BeforeToolCallResult | None:
        order.append(f"before:{ctx.tool_call.name}")
        return None

    async def after(ctx: AfterToolCallContext) -> AfterToolCallResult | None:
        order.append(f"after:{ctx.tool_call.name}")
        return AfterToolCallResult(content=f"after:{ctx.result.content}")

    tools = [
        AgentTool(name="echo", description="echo", execute=execute_echo),
    ]
    calls = [
        ToolCall(id="1", name="echo", arguments={"name": "a"}),
        ToolCall(id="2", name="echo", arguments={"name": "b"}),
    ]
    responses = [
        AssistantMessage(content=None, tool_calls=calls, stop_reason="toolUse"),
        AssistantMessage(content="done", stop_reason="stop"),
    ]

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        msg = responses.pop(0)
        yield AssistantStreamStart(partial=AssistantMessage(content=msg.content, tool_calls=[]))
        yield AssistantStreamDone(message=msg)

    events = [
        e
        async for e in agent_loop(
            [UserMessage(content="go")],
            AgentContext(tools=tools),
            AgentLoopConfig(
                convert_to_llm=default_convert_to_llm,
                tool_execution="sequential",
                before_tool_call=before,
                after_tool_call=after,
            ),
            stream_fn=stream_fn,
        )
    ]

    assert order == [
        "before:echo",
        "exec:a",
        "after:echo",
        "before:echo",
        "exec:b",
        "after:echo",
    ]
    types = [e.type for e in events]
    tool_end_idxs = [i for i, t in enumerate(types) if t == "tool_execution_end"]
    assert len(tool_end_idxs) == 2
    assert types[tool_end_idxs[0] + 1 : tool_end_idxs[0] + 3] == [
        "message_start",
        "message_end",
    ]
    first_result = events[tool_end_idxs[0] + 1]
    assert isinstance(first_result, MessageStartEvent)
    assert isinstance(first_result.message, ToolResultMessage)
    assert first_result.message.content == "after:ok:a"
    assert events[-1].type == "agent_end"


async def test_parallel_emits_end_in_completion_order_results_in_source_order() -> None:
    started = asyncio.Event()
    release_slow = asyncio.Event()

    async def execute_slow(tool_call_id: str, args: dict, **_kwargs) -> AgentToolResult:
        started.set()
        await release_slow.wait()
        return AgentToolResult(content="slow")

    async def execute_fast(tool_call_id: str, args: dict, **_kwargs) -> AgentToolResult:
        await started.wait()
        return AgentToolResult(content="fast")

    tools = [
        AgentTool(name="slow", execute=execute_slow),
        AgentTool(name="fast", execute=execute_fast),
    ]
    calls = [
        ToolCall(id="s", name="slow", arguments={}),
        ToolCall(id="f", name="fast", arguments={}),
    ]
    responses = [
        AssistantMessage(content=None, tool_calls=calls, stop_reason="toolUse"),
        AssistantMessage(content="done", stop_reason="stop"),
    ]

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        msg = responses.pop(0)
        yield AssistantStreamStart(partial=AssistantMessage())
        yield AssistantStreamDone(message=msg)

    async def collect() -> list:
        return [
            e
            async for e in agent_loop(
                [UserMessage(content="go")],
                AgentContext(tools=tools),
                AgentLoopConfig(
                    convert_to_llm=default_convert_to_llm,
                    tool_execution="parallel",
                ),
                stream_fn=stream_fn,
            )
        ]

    task = asyncio.create_task(collect())
    await started.wait()
    await asyncio.sleep(0.01)
    release_slow.set()
    events = await task

    end_names = [e.tool_name for e in events if isinstance(e, ToolExecutionEndEvent)]
    assert end_names == ["fast", "slow"]

    result_msgs = [
        e.message
        for e in events
        if isinstance(e, MessageStartEvent) and isinstance(e.message, ToolResultMessage)
    ]
    assert [m.tool_name for m in result_msgs] == ["slow", "fast"]
    assert [m.content for m in result_msgs] == ["slow", "fast"]


async def test_missing_required_argument_becomes_error_result() -> None:
    async def execute_boom(_id: str, _args: dict, **_kwargs) -> AgentToolResult:
        raise AssertionError("should not run")

    responses = [
        AssistantMessage(
            content=None,
            tool_calls=[ToolCall(id="1", name="need", arguments={})],
            stop_reason="toolUse",
        ),
        AssistantMessage(content="done", stop_reason="stop"),
    ]

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        msg = responses.pop(0)
        yield AssistantStreamStart(partial=AssistantMessage())
        yield AssistantStreamDone(message=msg)

    events = [
        e
        async for e in agent_loop(
            [UserMessage(content="go")],
            AgentContext(
                tools=[
                    AgentTool(
                        name="need",
                        parameters={"required": ["path"]},
                        execute=execute_boom,
                    )
                ]
            ),
            AgentLoopConfig(
                convert_to_llm=default_convert_to_llm,
                tool_execution="sequential",
            ),
            stream_fn=stream_fn,
        )
    ]
    ends = [e for e in events if isinstance(e, ToolExecutionEndEvent)]
    assert ends[0].is_error is True
    assert "path" in ends[0].result.content


async def test_before_hook_can_block_tool() -> None:
    async def execute_boom(_id: str, _args: dict, **_kwargs) -> AgentToolResult:
        raise AssertionError("should not run")

    async def before(_ctx: BeforeToolCallContext) -> BeforeToolCallResult:
        return BeforeToolCallResult(block=True, reason="nope")

    responses = [
        AssistantMessage(
            content=None,
            tool_calls=[ToolCall(id="1", name="boom", arguments={})],
            stop_reason="toolUse",
        ),
        AssistantMessage(content="done", stop_reason="stop"),
    ]

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        msg = responses.pop(0)
        yield AssistantStreamStart(partial=AssistantMessage())
        yield AssistantStreamDone(message=msg)

    events = [
        e
        async for e in agent_loop(
            [UserMessage(content="go")],
            AgentContext(tools=[AgentTool(name="boom", execute=execute_boom)]),
            AgentLoopConfig(
                convert_to_llm=default_convert_to_llm,
                tool_execution="sequential",
                before_tool_call=before,
            ),
            stream_fn=stream_fn,
        )
    ]
    ends = [e for e in events if isinstance(e, ToolExecutionEndEvent)]
    assert ends[0].is_error is True
    assert ends[0].result.content == "nope"


async def test_prompt_with_tools_emits_full_settled_event_sequence() -> None:
    async def execute(_id: str, _args: dict, **_k) -> AgentToolResult:
        return AgentToolResult(content="tool-out")

    responses = [
        AssistantMessage(
            content=None,
            tool_calls=[ToolCall(id="1", name="echo", arguments={"x": 1})],
            stop_reason="toolUse",
        ),
        AssistantMessage(content="final", stop_reason="stop"),
    ]

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        msg = responses.pop(0)
        yield AssistantStreamStart(partial=AssistantMessage())
        yield AssistantStreamDone(message=msg)

    events = [
        e
        async for e in agent_loop(
            [UserMessage(content="go")],
            AgentContext(tools=[AgentTool(name="echo", execute=execute)]),
            AgentLoopConfig(
                convert_to_llm=default_convert_to_llm,
                tool_execution="sequential",
            ),
            stream_fn=stream_fn,
        )
    ]

    assert [e.type for e in events] == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_end",
        "message_start",
        "message_end",
        "tool_execution_start",
        "tool_execution_end",
        "message_start",
        "message_end",
        "turn_end",
        "turn_start",
        "message_start",
        "message_end",
        "turn_end",
        "agent_end",
    ]


async def test_batch_terminate_skips_follow_up_llm_call() -> None:
    stream_calls = 0

    async def execute(_id: str, _args: dict, **_k) -> AgentToolResult:
        return AgentToolResult(content="bye", terminate=True)

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        nonlocal stream_calls
        stream_calls += 1
        msg = AssistantMessage(
            content=None,
            tool_calls=[ToolCall(id="1", name="done", arguments={})],
            stop_reason="toolUse",
        )
        yield AssistantStreamStart(partial=AssistantMessage())
        yield AssistantStreamDone(message=msg)

    events = [
        e
        async for e in agent_loop(
            [UserMessage(content="go")],
            AgentContext(tools=[AgentTool(name="done", execute=execute)]),
            AgentLoopConfig(
                convert_to_llm=default_convert_to_llm,
                tool_execution="sequential",
            ),
            stream_fn=stream_fn,
        )
    ]

    assert stream_calls == 1
    assert isinstance(events[-1], AgentEndEvent)
    assert isinstance(events[-2], TurnEndEvent)
