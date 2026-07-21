"""Seam: agent_loop public surface with injected fake StreamFn.

Prompt without tools emits the settled agent/turn/message event sequence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pi_agent.types import (
    AssistantStreamDone,
    AssistantStreamEvent,
    AssistantStreamStart,
    AssistantStreamTextDelta,
)

from pi_agent import (
    AgentContext,
    AgentEndEvent,
    AgentLoopConfig,
    AssistantMessage,
    MessageEndEvent,
    MessageStartEvent,
    StreamRequest,
    TurnEndEvent,
    UserMessage,
    agent_loop,
    default_convert_to_llm,
)


async def _fake_text_stream(
    request: StreamRequest,
) -> AsyncIterator[AssistantStreamEvent]:
    assert request.messages[-1].role == "user"
    partial = AssistantMessage(content="", stop_reason=None)
    yield AssistantStreamStart(partial=partial)
    partial = AssistantMessage(content="Hi", stop_reason=None)
    yield AssistantStreamTextDelta(partial=partial, delta="Hi")
    final = AssistantMessage(content="Hi", stop_reason="stop")
    yield AssistantStreamDone(message=final)


async def test_agent_loop_prompt_without_tools_emits_fixed_event_sequence() -> None:
    prompt = UserMessage(content="Hello")
    context = AgentContext(system_prompt="You are helpful.", messages=[])
    config = AgentLoopConfig(convert_to_llm=default_convert_to_llm)

    events = [
        event
        async for event in agent_loop(
            [prompt],
            context,
            config,
            stream_fn=_fake_text_stream,
        )
    ]

    types = [e.type for e in events]
    assert types == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_end",
        "message_start",
        "message_update",
        "message_end",
        "turn_end",
        "agent_end",
    ]
    assert isinstance(events[2], MessageStartEvent)
    assert events[2].message.content == "Hello"
    assert isinstance(events[6], MessageEndEvent)
    assert events[6].message.content == "Hi"
    assert isinstance(events[7], TurnEndEvent)
    assert events[7].tool_results == []
    assert isinstance(events[8], AgentEndEvent)
    assert events[8].messages[-1].content == "Hi"
