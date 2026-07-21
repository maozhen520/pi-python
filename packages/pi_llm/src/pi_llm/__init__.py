"""Thin LLM adapter (LiteLLM-backed OpenAI Chat Completions)."""

from pi_llm.capabilities import supports_parallel_tools, supports_tools
from pi_llm.complete import complete
from pi_llm.credentials import (
    apply_credentials_to_environ,
    default_auth_path,
    resolve_credentials,
)
from pi_llm.errors import ErrorKind, LLMError, map_provider_error
from pi_llm.stream import stream
from pi_llm.types import (
    AssistantMessage,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    TurnFinished,
)

__all__ = [
    "AssistantMessage",
    "ErrorKind",
    "LLMError",
    "StreamEvent",
    "TextDelta",
    "ToolCall",
    "ToolCallDelta",
    "TurnFinished",
    "apply_credentials_to_environ",
    "complete",
    "default_auth_path",
    "map_provider_error",
    "resolve_credentials",
    "stream",
    "supports_parallel_tools",
    "supports_tools",
]
