"""OpenAI-shaped error surface for provider/auth failures."""

from __future__ import annotations

from typing import Any

import pytest

from pi_llm import ErrorKind, LLMError, map_provider_error, stream


class AuthFailure(Exception):
    def __init__(self) -> None:
        super().__init__("Invalid API key")
        self.status_code = 401
        self.type = "invalid_request_error"
        self.code = "invalid_api_key"
        self.llm_provider = "openai"


def test_map_provider_error_preserves_openai_shape() -> None:
    err = map_provider_error(AuthFailure())
    assert isinstance(err, LLMError)
    assert err.status_code == 401
    assert err.message == "Invalid API key"
    assert err.type == "invalid_request_error"
    assert err.code == "invalid_api_key"
    assert err.llm_provider == "openai"
    assert err.kind is ErrorKind.AUTH


async def test_stream_maps_auth_failure_to_llm_error() -> None:
    async def boom(**_kwargs: Any) -> Any:
        raise AuthFailure()

    with pytest.raises(LLMError) as caught:
        async for _ in stream({"model": "test", "messages": []}, acompletion=boom):
            pass

    assert caught.value.status_code == 401
    assert caught.value.code == "invalid_api_key"
