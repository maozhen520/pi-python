"""Public types for the agent loop and stateful Agent SDK."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

StopReason = Literal["stop", "toolUse", "length", "error", "aborted"]
ToolExecutionMode = Literal["sequential", "parallel"]
QueueMode = Literal["all", "one-at-a-time"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserMessage:
    content: str
    role: Literal["user"] = "user"


@dataclass(slots=True)
class AssistantMessage:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: StopReason | None = None
    error_message: str | None = None
    role: Literal["assistant"] = "assistant"


@dataclass(slots=True)
class ToolResultMessage:
    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool = False
    details: Any = None
    role: Literal["toolResult"] = "toolResult"


@dataclass(slots=True)
class CustomMessage:
    """UI/app-only transcript message; must be filtered or mapped in convert_to_llm."""

    role: str
    content: Any = None
    data: dict[str, Any] = field(default_factory=dict)


LlmMessage = UserMessage | AssistantMessage | ToolResultMessage
AgentMessage = LlmMessage | CustomMessage


@dataclass(frozen=True, slots=True)
class AgentToolResult:
    content: str
    details: Any = None
    terminate: bool = False


@dataclass(slots=True)
class AgentTool:
    name: str
    description: str = ""
    label: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    execution_mode: ToolExecutionMode | None = None
    prepare_arguments: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    execute: Callable[..., Awaitable[AgentToolResult]] | None = None


@dataclass(slots=True)
class AgentContext:
    system_prompt: str = ""
    messages: list[AgentMessage] = field(default_factory=list)
    tools: list[AgentTool] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StreamRequest:
    """LLM-facing request built at the stream boundary after convert hooks."""

    system_prompt: str
    messages: list[LlmMessage]
    tools: list[AgentTool] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AssistantStreamStart:
    partial: AssistantMessage


@dataclass(frozen=True, slots=True)
class AssistantStreamTextDelta:
    partial: AssistantMessage
    delta: str


@dataclass(frozen=True, slots=True)
class AssistantStreamToolCallDelta:
    partial: AssistantMessage
    tool_call_id: str
    name: str | None = None
    arguments_delta: str | None = None


@dataclass(frozen=True, slots=True)
class AssistantStreamDone:
    message: AssistantMessage


@dataclass(frozen=True, slots=True)
class AssistantStreamError:
    message: AssistantMessage


AssistantStreamEvent = (
    AssistantStreamStart
    | AssistantStreamTextDelta
    | AssistantStreamToolCallDelta
    | AssistantStreamDone
    | AssistantStreamError
)


class StreamFn(Protocol):
    def __call__(
        self, request: StreamRequest
    ) -> AsyncIterator[AssistantStreamEvent] | Awaitable[AsyncIterator[AssistantStreamEvent]]: ...


@dataclass(frozen=True, slots=True)
class BeforeToolCallResult:
    block: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AfterToolCallResult:
    content: str | None = None
    details: Any = None
    is_error: bool | None = None
    terminate: bool | None = None


@dataclass(slots=True)
class BeforeToolCallContext:
    assistant_message: AssistantMessage
    tool_call: ToolCall
    args: dict[str, Any]
    context: AgentContext


@dataclass(slots=True)
class AfterToolCallContext:
    assistant_message: AssistantMessage
    tool_call: ToolCall
    args: dict[str, Any]
    result: AgentToolResult
    is_error: bool
    context: AgentContext


ConvertToLlm = Callable[
    [Sequence[AgentMessage]],
    Sequence[LlmMessage] | Awaitable[Sequence[LlmMessage]],
]
TransformContext = Callable[
    [Sequence[AgentMessage]],
    Sequence[AgentMessage] | Awaitable[Sequence[AgentMessage]],
]
BeforeToolCallFn = Callable[
    [BeforeToolCallContext],
    Awaitable[BeforeToolCallResult | None] | BeforeToolCallResult | None,
]
AfterToolCallFn = Callable[
    [AfterToolCallContext],
    Awaitable[AfterToolCallResult | None] | AfterToolCallResult | None,
]
MessageQueueFn = Callable[[], Awaitable[list[AgentMessage]] | list[AgentMessage]]


@dataclass(slots=True)
class AgentLoopConfig:
    convert_to_llm: ConvertToLlm
    transform_context: TransformContext | None = None
    tool_execution: ToolExecutionMode = "parallel"
    before_tool_call: BeforeToolCallFn | None = None
    after_tool_call: AfterToolCallFn | None = None
    get_steering_messages: MessageQueueFn | None = None
    get_follow_up_messages: MessageQueueFn | None = None
    should_stop_after_turn: Callable[..., Awaitable[bool] | bool] | None = None


@dataclass(frozen=True, slots=True)
class AgentStartEvent:
    type: Literal["agent_start"] = "agent_start"


@dataclass(frozen=True, slots=True)
class AgentEndEvent:
    messages: list[AgentMessage]
    type: Literal["agent_end"] = "agent_end"


@dataclass(frozen=True, slots=True)
class TurnStartEvent:
    type: Literal["turn_start"] = "turn_start"


@dataclass(frozen=True, slots=True)
class TurnEndEvent:
    message: AgentMessage
    tool_results: list[ToolResultMessage]
    type: Literal["turn_end"] = "turn_end"


@dataclass(frozen=True, slots=True)
class MessageStartEvent:
    message: AgentMessage
    type: Literal["message_start"] = "message_start"


@dataclass(frozen=True, slots=True)
class MessageUpdateEvent:
    message: AgentMessage
    assistant_message_event: AssistantStreamEvent
    type: Literal["message_update"] = "message_update"


@dataclass(frozen=True, slots=True)
class MessageEndEvent:
    message: AgentMessage
    type: Literal["message_end"] = "message_end"


@dataclass(frozen=True, slots=True)
class ToolExecutionStartEvent:
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    type: Literal["tool_execution_start"] = "tool_execution_start"


@dataclass(frozen=True, slots=True)
class ToolExecutionUpdateEvent:
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    partial_result: AgentToolResult
    type: Literal["tool_execution_update"] = "tool_execution_update"


@dataclass(frozen=True, slots=True)
class ToolExecutionEndEvent:
    tool_call_id: str
    tool_name: str
    result: AgentToolResult
    is_error: bool
    type: Literal["tool_execution_end"] = "tool_execution_end"


AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | TurnStartEvent
    | TurnEndEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
)


def default_convert_to_llm(messages: Sequence[AgentMessage]) -> list[LlmMessage]:
    return [
        m for m in messages if isinstance(m, (UserMessage, AssistantMessage, ToolResultMessage))
    ]
