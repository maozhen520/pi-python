"""OpenAI-shaped error surface for provider failures."""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorKind(Enum):
    """Coarse classification for retry / UX decisions."""

    AUTH = "auth"
    CONTEXT_WINDOW = "context_window"
    RATE_LIMIT = "rate_limit"
    RETRYABLE = "retryable"
    FATAL = "fatal"


class LLMError(Exception):
    """Thin, OpenAI-shaped error for callers (auth, rate limit, bad request, …)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        type: str | None = None,
        code: str | None = None,
        llm_provider: str | None = None,
        kind: ErrorKind = ErrorKind.FATAL,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.type = type
        self.code = code
        self.llm_provider = llm_provider
        self.kind = kind
        self.__cause__ = cause


def map_provider_error(exc: BaseException) -> LLMError:
    """Map a LiteLLM/OpenAI-style exception into `LLMError`."""
    if isinstance(exc, LLMError):
        return exc

    message = str(exc) or exc.__class__.__name__
    status_code = _attr_int(exc, "status_code")
    code = _attr_str(exc, "code")
    err_type = _attr_str(exc, "type") or _attr_str(exc, "error_type")
    return LLMError(
        message,
        status_code=status_code,
        type=err_type,
        code=code,
        llm_provider=_attr_str(exc, "llm_provider"),
        kind=_classify(exc, status_code=status_code, code=code, err_type=err_type),
        cause=exc,
    )


def _classify(
    exc: BaseException,
    *,
    status_code: int | None,
    code: str | None,
    err_type: str | None,
) -> ErrorKind:
    name = exc.__class__.__name__.lower()
    blob = " ".join(x for x in (name, code or "", err_type or "", str(exc).lower()) if x)

    if status_code in {401, 403} or "auth" in blob or "permission" in blob:
        return ErrorKind.AUTH
    if "contextwindow" in name or "context_window" in blob or "context length" in blob:
        return ErrorKind.CONTEXT_WINDOW
    if status_code == 429 or "ratelimit" in name or "rate_limit" in blob:
        return ErrorKind.RATE_LIMIT
    retry_names = ("timeout", "serviceunavailable", "apiconnection", "internalserver")
    if status_code in {408, 500, 502, 503, 504} or any(token in name for token in retry_names):
        return ErrorKind.RETRYABLE
    return ErrorKind.FATAL


def _attr_str(exc: BaseException, name: str) -> str | None:
    value: Any = getattr(exc, name, None)
    return value if isinstance(value, str) else None


def _attr_int(exc: BaseException, name: str) -> int | None:
    value: Any = getattr(exc, name, None)
    return value if isinstance(value, int) else None
