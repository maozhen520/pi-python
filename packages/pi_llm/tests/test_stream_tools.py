"""Stream boundary: assemble tool_calls before any execute handoff."""

from __future__ import annotations

from typing import Any

from pi_llm import TextDelta, ToolCallDelta, TurnFinished, stream


class _Fn:
    def __init__(self, name: str | None = None, arguments: str | None = None) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(
        self,
        index: int,
        *,
        id: str | None = None,
        name: str | None = None,
        arguments: str | None = None,
    ) -> None:
        self.index = index
        self.id = id
        self.type = "function"
        self.function = _Fn(name, arguments)


class _Delta:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[_ToolCall] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta: _Delta, finish_reason: str | None = None) -> None:
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(
        self,
        *,
        content: str | None = None,
        tool_calls: list[_ToolCall] | None = None,
        finish_reason: str | None = None,
    ) -> None:
        self.choices = [_Choice(_Delta(content, tool_calls), finish_reason)]


async def _fake_tool_stream(**_kwargs: Any) -> Any:
    async def _gen() -> Any:
        yield _Chunk(content="thinking…")
        yield _Chunk(
            tool_calls=[
                _ToolCall(0, id="call_a", name="read", arguments='{"path":'),
            ]
        )
        yield _Chunk(tool_calls=[_ToolCall(0, arguments='"a.txt"}')])
        yield _Chunk(
            tool_calls=[
                _ToolCall(1, id="call_b", name="bash", arguments='{"command":"ls"}'),
            ]
        )
        yield _Chunk(finish_reason="tool_calls")

    return _gen()


async def test_tool_calls_are_fully_assembled_on_turn_finished() -> None:
    seen_execute_ready = False
    events = []
    request = {"model": "test", "messages": [], "tools": []}
    async for event in stream(request, acompletion=_fake_tool_stream):
        events.append(event)
        if isinstance(event, TurnFinished):
            # Handoff point: arguments must be complete JSON strings.
            assert event.message.tool_calls[0].arguments == '{"path":"a.txt"}'
            assert event.message.tool_calls[1].arguments == '{"command":"ls"}'
            seen_execute_ready = True
        else:
            # Partials may stream for UI, but must not look like a finished turn.
            assert not isinstance(event, TurnFinished)

    assert seen_execute_ready
    assert any(isinstance(e, TextDelta) for e in events)
    assert any(isinstance(e, ToolCallDelta) for e in events)
    finished = next(e for e in events if isinstance(e, TurnFinished))
    assert finished.finish_reason == "tool_calls"
    assert [tc.name for tc in finished.message.tool_calls] == ["read", "bash"]
    assert [tc.id for tc in finished.message.tool_calls] == ["call_a", "call_b"]
