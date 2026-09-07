"""V2.0 销量反馈数据源（Protocol + 工厂 + Mock 实现）

切真实 Temu Order API 时只需新增 `TemuOrderSource`，环境变量切换：
  settings.FEEDBACK_SOURCE = temu_api  → 真实
  settings.FEEDBACK_SOURCE = mock      → 默认 mock（demo / 测试）
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass
class SalesRaw:
    """单商品单日原始销量数据（数据源与 DB 解耦的中间形态）"""
    platform_product_id: str
    date: str  # YYYY-MM-DD
    order_count: int
    refund_count: int
    rating: float | None
    category_rank: int | None


class FeedbackSource(Protocol):
    """销量数据源接口

    实现方必须保证：相同 (platform_product_id, date) 输入返回完全一致的行
    （即幂等 + 确定性），否则 sales_records 的 unique 约束会重复插入。
    """
    async def fetch(self, day: date, platform_product_ids: list[str]) -> list[SalesRaw]: ...
    @property
    def name(self) -> str: ...


# ============ Mock 数据源（PRD §19 默认）============
class MockOrderSource:
    """确定性 mock：用 platform_product_id 哈希作 PRNG 种子

    同一商品同一天 → 完全相同行
    30 天曲线模拟：订单 ~ Poisson(λ=3.5)，退款 ~ 5%，评分 ~ N(4.2, 0.6)
    """
    name = "mock"

    async def fetch(self, day: date, platform_product_ids: list[str]) -> list[SalesRaw]:
        results: list[SalesRaw] = []
        for pid in platform_product_ids:
            seed = int(hashlib.md5(f"{pid}|{day.isoformat()}".encode()).hexdigest()[:8], 16)
            rng = random.Random(seed)

            orders = _sample_poisson(rng, lam=3.5)
            refunds = min(orders, _sample_poisson(rng, lam=max(0.1, orders * 0.05)))
            rating = round(max(1.0, min(5.0, rng.gauss(4.2, 0.6))), 2)
            rank = rng.randint(1, 500)

            results.append(SalesRaw(
                platform_product_id=pid,
                date=day.isoformat(),
                order_count=orders,
                refund_count=refunds,
                rating=rating,
                category_rank=rank,
            ))
        return results


def _sample_poisson(rng: random.Random, lam: float) -> int:
    """Knuth 算法泊松采样（确定性的纯 Python，不依赖 numpy）"""
    import math
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


# ============ 工厂 ============
def get_source() -> FeedbackSource:
    """根据 settings.FEEDBACK_SOURCE 返回实现

    默认 mock — 没有真实 Temu 凭据时也可演示。
    真实切换：新增 `TemuOrderSource` 实现 + 在此处注册。
    """
    from app.core.config import settings
    backend = getattr(settings, "FEEDBACK_SOURCE", "mock")
    if backend == "mock":
        return MockOrderSource()
    raise NotImplementedError(f"FEEDBACK_SOURCE={backend} 暂未实现，目前仅 mock")