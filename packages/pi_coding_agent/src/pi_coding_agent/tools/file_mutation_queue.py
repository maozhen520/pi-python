"""Serialize file mutations targeting the same realpath."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

_queues: dict[str, asyncio.Lock] = {}
_registry_lock = asyncio.Lock()


async def _queue_key(file_path: Path) -> str:
    resolved = file_path if file_path.is_absolute() else file_path.resolve()
    try:
        return str(resolved.resolve(strict=True))
    except (FileNotFoundError, OSError):
        return str(resolved)


async def with_file_mutation_queue(file_path: Path | str, fn: Callable[[], Awaitable[T]]) -> T:
    path = Path(file_path)
    async with _registry_lock:
        key = await _queue_key(path)
        lock = _queues.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _queues[key] = lock
    async with lock:
        return await fn()
