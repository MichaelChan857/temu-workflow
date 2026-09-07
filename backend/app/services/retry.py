"""发布重试 — 指数退避 + 抖动 + 幂等键复用

PRD §11 / FR-087 / FR-089 / L23
"""
import asyncio
import random
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Any
from datetime import datetime, timezone

log = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_sec: float = 1.0
    max_delay_sec: float = 60.0
    jitter_ratio: float = 0.2  # ±20% 随机


def compute_backoff(attempt: int, policy: RetryPolicy) -> float:
    """指数退避 + 抖动

    attempt: 从 1 开始（第一次重试）
    delay = min(base * 2^(attempt-1), max_delay) * (1 ± jitter)
    """
    base = min(policy.base_delay_sec * (2 ** (attempt - 1)), policy.max_delay_sec)
    jitter = base * policy.jitter_ratio * (random.random() * 2 - 1)
    return max(0.1, base + jitter)


# ============ 错误分类 ============
ERROR_CLASSES = {"retryable", "fatal", "need_auth", "need_fix"}


def should_retry(error_class: str, attempt: int, policy: RetryPolicy) -> bool:
    """判断是否应该重试

    retryable + 未超 max_attempts → 重试
    其他 3 类 → 不重试
    """
    if error_class != "retryable":
        return False
    if attempt >= policy.max_attempts:
        return False
    return True


# ============ 重试执行器 ============
async def with_retry(
    func: Callable,
    policy: RetryPolicy,
    on_retry: Optional[Callable] = None,
    *args,
    **kwargs,
) -> tuple[bool, Any, dict]:
    """带重试地执行 async 函数

    Args:
        func: async 函数，返回 (error_class: str, result: Any)
        on_retry: 每次重试前的回调 (attempt, delay, error_class)
        *args, **kwargs: 传给 func

    Returns:
        (success, result_or_error, meta)
        - success: True/False
        - result: 成功时为返回值；失败时为 {"error_class", "error_message", "attempts"}
        - meta: {"attempts": int, "delays": [...], "final_error_class": str}
    """
    delays = []
    attempts = 0
    last_error_class = None
    last_error_msg = None

    for attempt in range(1, policy.max_attempts + 2):  # +1 留给最终尝试
        attempts = attempt
        try:
            error_class, result = await func(*args, **kwargs)
        except Exception as e:
            error_class = "retryable"
            result = {"error_class": error_class, "error_message": str(e)}
            last_error_msg = str(e)

        if error_class is None or error_class == "success":
            return True, result, {
                "attempts": attempts,
                "delays": delays,
                "final_error_class": None,
            }

        last_error_class = error_class
        last_error_msg = (result or {}).get("error_message") or str(result)

        # 不重试
        if not should_retry(error_class, attempt, policy):
            break

        # 计算延迟
        delay = compute_backoff(attempt, policy)
        delays.append(delay)

        if on_retry:
            try:
                await on_retry(attempt, delay, error_class)
            except Exception:
                pass

        log.info(f"retry attempt={attempt + 1} delay={delay:.2f}s error_class={error_class}")
        await asyncio.sleep(delay)

    return False, {
        "error_class": last_error_class,
        "error_message": last_error_msg,
    }, {
        "attempts": attempts,
        "delays": delays,
        "final_error_class": last_error_class,
    }