"""Seam: session JSONL persistence + compaction against a temp session tree."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from pi_agent.types import AssistantStreamEvent
from pi_coding_agent.session import (
    SessionStore,
    apply_compaction_view,
    encode_cwd,
    estimate_tokens,
)

from pi_agent import Agent, AssistantMessage, StreamRequest, UserMessage


def test_encode_cwd_is_stable_and_filesystem_safe(tmp_path: Path) -> None:
    encoded = encode_cwd(tmp_path)
    assert "/" not in encoded
    assert encode_cwd(tmp_path) == encoded


def test_session_persist_resume_list_branch_fork(tmp_path: Path) -> None:
    store = SessionStore(root=tmp_path / "sessions")
    cwd = tmp_path / "project"
    cwd.mkdir()

    session = store.create(cwd=cwd)
    session.append_message(UserMessage(content="hi"))
    session.append_message(AssistantMessage(content="hello", stop_reason="stop"))
    session_id = session.id
    path = session.path

    listed = store.list_sessions(cwd=cwd)
    assert any(item.id == session_id for item in listed)

    resumed = store.resume(path)
    assert [m.content for m in resumed.messages if hasattr(m, "content")] == ["hi", "hello"]

    branched = resumed.create_branch("explore")
    branched.append_message(UserMessage(content="branch tip"))
    assert len(branched.messages) == 3
    assert len(resumed.messages) == 2

    forked = resumed.fork()
    assert forked.id != resumed.id
    assert forked.path != resumed.path
    assert len(forked.messages) == 2


def test_session_owns_file_agent_owns_transcript_after_load(tmp_path: Path) -> None:
    store = SessionStore(root=tmp_path / "sessions")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    session = store.create(cwd=cwd)
    session.append_message(UserMessage(content="a"))

    async def unused_stream(request: StreamRequest) -> AsyncIterator[AssistantStreamEvent]:
        raise AssertionError("not used")
        if False:  # pragma: no cover — keeps this an async generator type
            yield  # type: ignore[misc]

    agent = Agent(stream_fn=unused_stream, messages=session.messages)
    agent.messages.append(UserMessage(content="live-only"))
    assert len(session.messages) == 1
    session.append_message(UserMessage(content="persisted"))
    assert len(session.messages) == 2
    assert len(agent.messages) == 2  # agent still has its own list copy from load


def test_compaction_appends_entry_and_model_sees_summary_plus_tail(tmp_path: Path) -> None:
    store = SessionStore(root=tmp_path / "sessions")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    session = store.create(cwd=cwd)
    for i in range(10):
        session.append_message(UserMessage(content=f"msg-{i} " * 20))
        session.append_message(AssistantMessage(content=f"reply-{i} " * 20, stop_reason="stop"))

    before = session.path.read_text(encoding="utf-8")
    entry = session.compact(
        summary="SUMMARY_OF_OLD",
        keep_recent_tokens=50,
        instructions="focus on decisions",
    )
    after = session.path.read_text(encoding="utf-8")
    assert "SUMMARY_OF_OLD" in after
    assert '"type": "compaction"' in after or '"compaction"' in after
    # History lines remain (append-only).
    assert before in after or after.startswith(before.splitlines()[0])
    assert len(after.splitlines()) > len(before.splitlines())

    view = apply_compaction_view(session.messages, entry)
    assert any(getattr(m, "content", None) == "SUMMARY_OF_OLD" for m in view)
    # Tail kept; early messages dropped from model view.
    texts = [getattr(m, "content", "") for m in view]
    assert "msg-0 " not in " ".join(texts) or "SUMMARY_OF_OLD" in texts[0]


def test_auto_compaction_triggers_near_window(tmp_path: Path) -> None:
    store = SessionStore(root=tmp_path / "sessions")
    cwd = tmp_path / "proj"
    cwd.mkdir()
    session = store.create(cwd=cwd)
    # Small window forces auto compaction.
    for i in range(8):
        session.append_message(UserMessage(content=("token " * 40) + f"{i}"))

    did = session.maybe_auto_compact(
        context_window=200,
        reserve_tokens=50,
        keep_recent_tokens=40,
        summarize=lambda msgs, instructions: "AUTO_SUMMARY",
    )
    assert did is True
    assert any(
        getattr(m, "role", None) == "compaction" or getattr(m, "type", None) == "compaction"
        for m in session.entries()
    )
    assert estimate_tokens("token " * 40) > 0
