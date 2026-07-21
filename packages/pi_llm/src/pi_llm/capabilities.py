"""Model capability probes (tools / parallel tools)."""

from __future__ import annotations

from collections.abc import Callable

Probe = Callable[[str], bool]


def supports_tools(model: str, *, probe: Probe | None = None) -> bool:
    """Return whether `model` supports structured function/tool calling."""
    fn = probe or _default_supports_function_calling
    try:
        return bool(fn(model))
    except Exception:
        return False


def supports_parallel_tools(model: str, *, probe: Probe | None = None) -> bool:
    """Return whether `model` supports parallel tool calls."""
    fn = probe or _default_supports_parallel_function_calling
    try:
        return bool(fn(model))
    except Exception:
        return False


def _default_supports_function_calling(model: str) -> bool:
    from litellm import supports_function_calling

    return bool(supports_function_calling(model=model))


def _default_supports_parallel_function_calling(model: str) -> bool:
    from litellm import supports_parallel_function_calling

    return bool(supports_parallel_function_calling(model=model))
