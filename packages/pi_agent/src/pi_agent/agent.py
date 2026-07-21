"""Stateful Agent facade over the pure agent loop."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import cast

from pi_agent.loop import run_agent_loop, run_agent_loop_continue
from pi_agent.types import (
    AfterToolCallFn,
    AgentContext,
    AgentEndEvent,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentTool,
    BeforeToolCallFn,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    QueueMode,
    StreamFn,
    ToolExecutionMode,
    UserMessage,
    default_convert_to_llm,
)

Listener = Callable[[AgentEvent], Awaitable[None] | None]


class _PendingQueue:
    def __init__(self, mode: QueueMode = "one-at-a-time") -> None:
        self.mode = mode
        self._messages: list[AgentMessage] = []

    def enqueue(self, message: AgentMessage) -> None:
        self._messages.append(message)

    def has_items(self) -> bool:
        return bool(self._messages)

    def drain(self) -> list[AgentMessage]:
        if self.mode == "all":
            drained = list(self._messages)
            self._messages.clear()
            return drained
        if not self._messages:
            return []
        first = self._messages.pop(0)
        return [first]

    def clear(self) -> None:
        self._messages.clear()


class Agent:
    """Owns transcript/tools/queues; awaits subscribe listeners as settlement barrier."""

    def __init__(
        self,
        *,
        stream_fn: StreamFn,
        system_prompt: str = "",
        tools: Sequence[AgentTool] | None = None,
        messages: Sequence[AgentMessage] | None = None,
        convert_to_llm: Callable | None = None,
        transform_context: Callable | None = None,
        before_tool_call: BeforeToolCallFn | None = None,
        after_tool_call: AfterToolCallFn | None = None,
        tool_execution: ToolExecutionMode = "parallel",
        steering_mode: QueueMode = "one-at-a-time",
        follow_up_mode: QueueMode = "one-at-a-time",
    ) -> None:
        self.stream_fn = stream_fn
        self.system_prompt = system_prompt
        self._tools = list(tools or [])
        self._messages = list(messages or [])
        self.convert_to_llm = convert_to_llm or default_convert_to_llm
        self.transform_context = transform_context
        self.before_tool_call = before_tool_call
        self.after_tool_call = after_tool_call
        self.tool_execution = tool_execution
        self._steering = _PendingQueue(steering_mode)
        self._follow_up = _PendingQueue(follow_up_mode)
        self._listeners: list[Listener] = []
        self._active = False
        self._streaming_message: AgentMessage | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def messages(self) -> list[AgentMessage]:
        return self._messages

    @messages.setter
    def messages(self, value: Sequence[AgentMessage]) -> None:
        self._messages = list(value)

    @property
    def tools(self) -> list[AgentTool]:
        return self._tools

    @tools.setter
    def tools(self, value: Sequence[AgentTool]) -> None:
        self._tools = list(value)

    @property
    def is_streaming(self) -> bool:
        return self._active

    @property
    def streaming_message(self) -> AgentMessage | None:
        return self._streaming_message

    @property
    def steering_mode(self) -> QueueMode:
        return self._steering.mode

    @steering_mode.setter
    def steering_mode(self, mode: QueueMode) -> None:
        self._steering.mode = mode

    @property
    def follow_up_mode(self) -> QueueMode:
        return self._follow_up.mode

    @follow_up_mode.setter
    def follow_up_mode(self, mode: QueueMode) -> None:
        self._follow_up.mode = mode

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def steer(self, message: AgentMessage) -> None:
        self._steering.enqueue(message)

    def follow_up(self, message: AgentMessage) -> None:
        self._follow_up.enqueue(message)

    def clear_steering_queue(self) -> None:
        self._steering.clear()

    def clear_follow_up_queue(self) -> None:
        self._follow_up.clear()

    def clear_all_queues(self) -> None:
        self.clear_steering_queue()
        self.clear_follow_up_queue()

    async def wait_for_idle(self) -> None:
        await self._idle.wait()

    async def prompt(self, input: str | AgentMessage | Sequence[AgentMessage]) -> None:
        if self._active:
            raise RuntimeError(
                "Agent is already processing a prompt. Use steer() or follow_up() "
                "to queue messages, or wait for completion."
            )
        messages = self._normalize_prompt(input)
        await self._run_prompt_messages(messages)

    async def continue_(self) -> None:
        """Continue from current transcript without appending a new user message."""
        if self._active:
            raise RuntimeError(
                "Agent is already processing. Wait for completion before continuing."
            )

        if not self._messages:
            raise ValueError("No messages to continue from")

        last = self._messages[-1]
        if last.role == "assistant":
            steered = self._steering.drain()
            if steered:
                await self._run_prompt_messages(steered, skip_initial_steering_poll=True)
                return
            follow = self._follow_up.drain()
            if follow:
                await self._run_prompt_messages(follow)
                return
            raise ValueError("Cannot continue from message role: assistant")

        await self._run_continuation()

    def _normalize_prompt(
        self, input: str | AgentMessage | Sequence[AgentMessage]
    ) -> list[AgentMessage]:
        if isinstance(input, str):
            return [UserMessage(content=input)]
        if isinstance(input, list):
            return cast(list[AgentMessage], list(input))
        if isinstance(input, tuple):
            return cast(list[AgentMessage], list(input))
        return [cast(AgentMessage, input)]

    async def _run_prompt_messages(
        self,
        messages: list[AgentMessage],
        *,
        skip_initial_steering_poll: bool = False,
    ) -> None:
        await self._run_with_lifecycle(
            lambda: run_agent_loop(
                messages,
                self._context_snapshot(),
                self._loop_config(skip_initial_steering_poll=skip_initial_steering_poll),
                self._process_events,
                self.stream_fn,
            )
        )

    async def _run_continuation(self) -> None:
        await self._run_with_lifecycle(
            lambda: run_agent_loop_continue(
                self._context_snapshot(),
                self._loop_config(),
                self._process_events,
                self.stream_fn,
            )
        )

    def _context_snapshot(self) -> AgentContext:
        return AgentContext(
            system_prompt=self.system_prompt,
            messages=list(self._messages),
            tools=list(self._tools),
        )

    def _loop_config(self, *, skip_initial_steering_poll: bool = False) -> AgentLoopConfig:
        skip = skip_initial_steering_poll

        async def get_steering() -> list[AgentMessage]:
            nonlocal skip
            if skip:
                skip = False
                return []
            return self._steering.drain()

        async def get_follow_up() -> list[AgentMessage]:
            return self._follow_up.drain()

        return AgentLoopConfig(
            convert_to_llm=self.convert_to_llm,
            transform_context=self.transform_context,
            tool_execution=self.tool_execution,
            before_tool_call=self.before_tool_call,
            after_tool_call=self.after_tool_call,
            get_steering_messages=get_steering,
            get_follow_up_messages=get_follow_up,
        )

    async def _run_with_lifecycle(self, executor: Callable[[], Awaitable[object]]) -> None:
        if self._active:
            raise RuntimeError("Agent is already processing.")
        self._active = True
        self._idle.clear()
        try:
            await executor()
        finally:
            self._active = False
            self._idle.set()

    async def _process_events(self, event: AgentEvent) -> None:
        if isinstance(event, (MessageStartEvent, MessageUpdateEvent)):
            self._streaming_message = event.message
        elif isinstance(event, MessageEndEvent):
            # Barrier: transcript includes the message before tool preflight / later phases.
            self._streaming_message = None
            self._messages.append(event.message)
        elif isinstance(event, AgentEndEvent):
            self._streaming_message = None
        for listener in list(self._listeners):
            result = listener(event)
            if inspect.isawaitable(result):
                await result


# `continue` is a Python keyword; expose the upstream method name via setattr.
setattr(Agent, "continue", Agent.continue_)
