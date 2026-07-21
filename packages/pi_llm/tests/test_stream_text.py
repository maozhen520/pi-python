"""Stream boundary: incremental assistant text for UI (fixtures only)."""

from __future__ import annotations

from typing import Any

from pi_llm import TextDelta, TurnFinished, stream


class _Delta:
    def __init__(self, content: str | None = None) -> None:
        self.content = content
        self.tool_calls = None
        self.role = "assistant"


class _Choice:
    def __init__(self, delta: _Delta, finish_reason: str | None = None) -> None:
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, content: str | None = None, finish_reason: str | None = None) -> None:
        self.choices = [_Choice(_Delta(content), finish_reason)]


async def _fake_text_stream(**_kwargs: Any) -> Any:
    async def _gen() -> Any:
        yield _Chunk("Hel")
        yield _Chunk("lo")
        yield _Chunk(None, finish_reason="stop")

    return _gen()


async def test_stream_yields_text_deltas_then_turn_finished() -> None:
    request = {"model": "test", "messages": []}
    events = [event async for event in stream(request, acompletion=_fake_text_stream)]

    texts = [e.text for e in events if isinstance(e, TextDelta)]
    assert texts == ["Hel", "lo"]

    finished = [e for e in events if isinstance(e, TurnFinished)]
    assert len(finished) == 1
    assert finished[0].message.content == "Hello"
    assert finished[0].message.tool_calls == []
    assert finished[0].finish_reason == "stop"
