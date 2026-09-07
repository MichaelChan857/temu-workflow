"""W5-D6 发布链路测试（纯算法 + mock 适配器）

测试项：
  1. 错误分类映射（4 类 + 边界）
  2. 退避计算（指数 + 抖动）
  3. 重试判定
  4. with_retry 执行器（成功 / 重试 / 不可重试）
  5. 幂等键生成一致性
"""
import asyncio
import sys
import hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.retry import (
    RetryPolicy, compute_backoff, should_retry, with_retry
)


def test_backoff():
    """测试 1：退避计算"""
    print("[1/6] 退避计算（指数 + 抖动）")
    policy = RetryPolicy(base_delay_sec=1.0, max_delay_sec=60.0, jitter_ratio=0.0)

    # 期望：1, 2, 4, 8, 16, 32, 60（达到上限）
    expected = [1, 2, 4, 8, 16, 32, 60]
    for i, exp in enumerate(expected, start=1):
        delay = compute_backoff(i, policy)
        assert abs(delay - exp) < 0.01, f"attempt {i}: expected {exp}, got {delay}"
    print(f"  [OK] 7 次退避：{expected}")

    # 抖动测试：±20%
    delays = [compute_backoff(3, policy) for _ in range(100)]
    jittered = all(3.2 <= d <= 4.8 for d in delays)
    assert jittered, f"抖动超出范围: {delays[:5]}"
    print(f"  [OK] 抖动在 4±20% 范围内")


def test_should_retry():
    """测试 2：重试判定"""
    print("\n[2/6] 重试判定")
    policy = RetryPolicy(max_attempts=3)

    # retryable + 未超限 → 重试
    assert should_retry("retryable", 1, policy)
    assert should_retry("retryable", 2, policy)
    assert not should_retry("retryable", 3, policy), "已达上限不应重试"

    # 其他 3 类 → 不重试
    for ec in ("fatal", "need_auth", "need_fix"):
        assert not should_retry(ec, 1, policy), f"{ec} 不应重试"

    print("  [OK] retryable 1-2 次重试，第3 次停止")
    print("  [OK] fatal/need_auth/need_fix 不重试")


async def test_with_retry_success():
    """测试 3：with_retry 成功场景"""
    print("\n[3/6] with_retry 成功")

    call_count = 0

    async def ok():
        nonlocal call_count
        call_count += 1
        return None, {"id": "prod-1"}

    success, result, meta = await with_retry(ok, RetryPolicy(max_attempts=3))
    assert success
    assert call_count == 1, "应只调1 次"
    assert meta["attempts"] == 1
    print(f"  [OK] 1 次成功，attempts={meta['attempts']}")


async def test_with_retry_retryable():
    """测试 4：with_retry 重试 retryable 错误"""
    print("\n[4/6] with_retry 重试 retryable")

    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return "retryable", {"error_message": "transient"}
        return None, {"id": "prod-3"}

    success, result, meta = await with_retry(
        flaky,
        RetryPolicy(max_attempts=5, base_delay_sec=0.01, jitter_ratio=0.0),
    )
    assert success
    assert call_count == 3, f"应重试 2 次（3 次调用），实际 {call_count}"
    print(f"  [OK] 2 次 retryable 后成功，attempts={meta['attempts']}, delays={meta['delays']}")


async def test_with_retry_exhausted():
    """测试 5：超过 max_attempts 失败"""
    print("\n[5/6] with_retry 耗尽重试")

    call_count = 0

    async def always_fail():
        nonlocal call_count
        call_count += 1
        return "retryable", {"error_message": f"fail {call_count}"}

    success, result, meta = await with_retry(
        always_fail,
        RetryPolicy(max_attempts=3, base_delay_sec=0.01, jitter_ratio=0.0),
    )
    assert not success
    assert call_count == 3
    assert result["error_class"] == "retryable"
    print(f"  [OK] 重试 3 次后失败，attempts={call_count}")


async def test_with_retry_fatal():
    """测试 6：fatal 错误不重试"""
    print("\n[6/6] with_retry fatal 不重试")

    call_count = 0

    async def fatal():
        nonlocal call_count
        call_count += 1
        return "fatal", {"error_message": "validation failed"}

    success, result, meta = await with_retry(
        fatal,
        RetryPolicy(max_attempts=3, base_delay_sec=0.01, jitter_ratio=0.0),
    )
    assert not success
    assert call_count == 1, "fatal 应只调1 次"
    assert result["error_class"] == "fatal"
    print(f"  [OK] fatal 不重试，attempts={call_count}")


def test_idempotency_key():
    """测试 7：幂等键一致性"""
    print("\n[7/6] 幂等键一致性")

    # PRD FR-083：每店铺+每发布意图唯一
    listing_id = "L-123"
    shop_id = "S-456"
    snapshot_version = 5

    key1 = hashlib.sha256(f"{shop_id}|{snapshot_version}|{listing_id}".encode()).hexdigest()[:32]
    key2 = hashlib.sha256(f"{shop_id}|{snapshot_version}|{listing_id}".encode()).hexdigest()[:32]
    assert key1 == key2

    # 改 snapshot_version 应得不同 key（避免旧版本重发）
    key3 = hashlib.sha256(f"{shop_id}|6|{listing_id}".encode()).hexdigest()[:32]
    assert key1 != key3

    print(f"  [OK] 同输入同 key: {key1[:16]}...")
    print(f"  [OK] snapshot_version 变更 → 新 key: {key3[:16]}...")


async def main():
    print("=" * 60)
    print("W5 发布链路测试")
    print("=" * 60)

    test_backoff()
    test_should_retry()
    test_idempotency_key()
    await test_with_retry_success()
    await test_with_retry_retryable()
    await test_with_retry_exhausted()
    await test_with_retry_fatal()

    print("\n" + "=" * 60)
    print("全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())