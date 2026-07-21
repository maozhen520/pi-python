"""Non-stream completion surface (fixtures only)."""

from __future__ import annotations

from typing import Any

from pi_llm import TurnFinished, complete


class _Fn:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.function = _Fn(name, arguments)


class _Message:
    def __init__(self, content: str | None, tool_calls: list[_ToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message: _Message, finish_reason: str) -> None:
        self.message = message
        self.finish_reason = finish_reason


class _Response:
    def __init__(self, choice: _Choice) -> None:
        self.choices = [choice]
        self.usage = None


async def _fake_complete(**kwargs: Any) -> Any:
    assert kwargs.get("stream") is False
    assert kwargs.get("tools") is not None
    return _Response(
        _Choice(
            _Message(
                content=None,
                tool_calls=[_ToolCall("c1", "read", '{"path":"x"}')],
            ),
            "tool_calls",
        )
    )


async def test_complete_returns_assembled_tool_calls() -> None:
    turn = await complete(
        {"model": "test", "messages": [], "tools": [{"type": "function"}], "tool_choice": "auto"},
        acompletion=_fake_complete,
    )
    assert isinstance(turn, TurnFinished)
    assert turn.finish_reason == "tool_calls"
    assert turn.message.tool_calls[0].name == "read"
    assert turn.message.tool_calls[0].arguments == '{"path":"x"}'
