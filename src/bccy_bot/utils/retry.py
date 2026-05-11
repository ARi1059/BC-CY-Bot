"""Telegram API 调用的指数退避重试装饰器。"""

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import TypeVar

import structlog
from telegram.error import NetworkError, RetryAfter, TimedOut

log = structlog.get_logger()

T = TypeVar("T")


def telegram_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    捕获临时性 Telegram 错误（网络抖动、超时、被限流），指数退避重试。

    REQ §4.3：所有 Telegram API 调用须带重试 (最多 3 次)。
    永久性错误（BadRequest 等）不重试，直接抛出由上层处理。
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except RetryAfter as e:
                    # Telegram 显式告诉了等待秒数
                    delay = min(float(e.retry_after) + 0.5, max_delay)
                    log.warning(
                        "telegram_retry_after",
                        func=func.__name__,
                        attempt=attempt,
                        wait=delay,
                    )
                    last_exc = e
                except (TimedOut, NetworkError) as e:
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    log.warning(
                        "telegram_retry_transient",
                        func=func.__name__,
                        attempt=attempt,
                        err=type(e).__name__,
                        wait=delay,
                    )
                    last_exc = e

                if attempt == max_attempts:
                    break
                await asyncio.sleep(delay)

            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
