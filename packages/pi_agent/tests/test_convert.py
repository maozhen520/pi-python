"""Seam: AgentMessage stays in transcript; LLM Messages only at stream time."""

from __future__ import annotations

from collections.abc import AsyncIterator

from pi_agent.types import (
    AssistantStreamDone,
    AssistantStreamEvent,
    AssistantStreamStart,
)

from pi_agent import (
    AgentContext,
    AgentEndEvent,
    AgentLoopConfig,
    AssistantMessage,
    CustomMessage,
    StreamRequest,
    UserMessage,
    agent_loop,
    default_convert_to_llm,
)


async def test_custom_messages_filtered_before_stream() -> None:
    seen: list[StreamRequest] = []

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        seen.append(request)
        final = AssistantMessage(content="ok", stop_reason="stop")
        yield AssistantStreamStart(partial=AssistantMessage(content=""))
        yield AssistantStreamDone(message=final)

    context = AgentContext(
        system_prompt="sys",
        messages=[CustomMessage(role="notification", content="ignore me")],
    )
    prompt = UserMessage(content="hi")
    config = AgentLoopConfig(
        convert_to_llm=default_convert_to_llm,
        transform_context=lambda msgs: [m for m in msgs if getattr(m, "role", None) != "noise"],
    )

    events = [
        e
        async for e in agent_loop(
            [prompt, CustomMessage(role="noise", content="drop")],
            context,
            config,
            stream_fn=stream_fn,
        )
    ]

    assert seen[0].messages == [UserMessage(content="hi")]
    assert all(m.role != "notification" for m in seen[0].messages)
    assert isinstance(events[-1], AgentEndEvent)
    roles = [m.role for m in events[-1].messages]
    assert "noise" in roles
    assert "user" in roles
