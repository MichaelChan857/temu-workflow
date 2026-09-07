"""V2.0 评分校准引擎（PRD §19）

三个纯函数：
- compute_realized_score(records)   → 0-100 标量
- dimension_errors(pred, realized)  → {dim: bias}
- recommend_adjustments(errors, w, lr) → {dim: new_weight}

一个 DB 函数：
- run_calibration(db, window_days, end_day) → ModelDrift row

关键不变量（PRD §6.5）：校准只产出报告，不自动激活任何配置。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date as _date, timedelta
from typing import Iterable
from uuid import uuid4 as _uuid4  # Event.entity_id 占位 UUID（drift.id 是 int）

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConfigVersion,
    Event,
    ListingDraft,
    ModelDrift,
    ProductScore,
    SalesRecord,
)

DIMENSIONS = ("heat", "competition", "profit", "trend", "ratings", "risk")
MIN_SAMPLE_SIZE = 5  # 样本过少时不推荐权重调整


# ============ 纯函数 1: realized score（0-100 标量）============
def compute_realized_score(records: list[dict]) -> float:
    """把 30 天销量转成一个 0-100 分

    公式：0.40·log10(orders+1)·25 + 0.25·refund_penalty + 0.20·rating_norm + 0.15·rank_norm
    """
    if not records:
        return 0.0

    total_orders = sum(r.get("order_count", 0) for r in records)
    total_refunds = sum(r.get("refund_count", 0) for r in records)
    avg_rating = sum(r.get("rating") or 0.0 for r in records) / len(records)
    avg_rank = sum(r.get("category_rank") or 250 for r in records) / len(records)

    order_term = 0.40 * math.log10(total_orders + 1) * 25
    refund_rate = total_refunds / max(total_orders, 1)
    refund_term = 0.25 * max(0.0, (1.0 - refund_rate)) * 100  # 退款少 → 高分
    rating_term = 0.20 * (avg_rating / 5.0) * 100
    rank_term = 0.15 * max(0.0, (1.0 - avg_rank / 500.0)) * 100

    score = order_term + refund_term + rating_term + rank_term
    return max(0.0, min(100.0, score))


# ============ 纯函数 2: dimension-level bias ============
def dimension_errors(
    predicted_dim_scores: dict,
    realized_components: dict,
) -> dict:
    """每维 bias = realized_component - predicted_dim_score

    realized_components 应包含 6 个维度的 0-100 实现值：
    {"heat": orders_velocity, "competition": refund_signal, "profit": rating_signal,
     "trend": rank_signal, "ratings": avg_rating_norm, "risk": refund_rate_inverse}
    """
    result = {}
    for dim in DIMENSIONS:
        pred = predicted_dim_scores.get(dim)
        real = realized_components.get(dim)
        if pred is None or real is None:
            continue
        result[dim] = round(real - pred, 2)
    return result


def compute_realized_components(records: list[dict]) -> dict:
    """把销量记录摊成 6 维实现分量（与 ProductScore.dimension_scores 同结构）"""
    if not records:
        return {}
    total_orders = sum(r.get("order_count", 0) for r in records)
    total_refunds = sum(r.get("refund_count", 0) for r in records)
    avg_rating = sum(r.get("rating") or 0.0 for r in records) / len(records)
    avg_rank = sum(r.get("category_rank") or 250 for r in records) / len(records)

    # 6 维 — 与 ProductScore 的 heat/competition/profit/trend/ratings/risk 对齐
    heat = min(100.0, math.log10(total_orders + 1) * 35)  # 流量热度
    competition = max(0.0, 100.0 - (avg_rank / 5.0))  # 类目内排名 → 竞争烈度反向
    profit = min(100.0, (avg_rating or 0.0) * 20)  # 评分 → 利润率代理
    trend = min(100.0, math.log10(total_orders + 1) * 40)  # 增长趋势
    ratings = (avg_rating / 5.0) * 100  # 评分本身
    refund_rate = total_refunds / max(total_orders, 1)
    risk = max(0.0, (1.0 - refund_rate) * 100)  # 退款少 → 风险低

    return {
        "heat": round(heat, 2),
        "competition": round(competition, 2),
        "profit": round(profit, 2),
        "trend": round(trend, 2),
        "ratings": round(ratings, 2),
        "risk": round(risk, 2),
    }


# ============ 纯函数 3: 推荐权重调整 ============
def recommend_adjustments(
    dimension_errors: dict,
    current_weights: dict,
    lr: float = 0.05,
    cap: float = 0.05,
) -> dict:
    """单步调整：new_w = w - lr·sign(bias)，单步限幅 ±cap，归一化和 = 1

    bias > 0 表示预测过低（实现比预测好），应增加该维权重
    bias < 0 表示预测过高，应降低权重
    """
    raw = {}
    for dim in DIMENSIONS:
        w = current_weights.get(dim, 0.0)
        bias = dimension_errors.get(dim, 0.0)
        # bias 正向 → 该维实际比预测好 → 提升权重
        delta = lr * (1.0 if bias > 0 else -1.0 if bias < 0 else 0.0)
        delta = max(-cap, min(cap, delta))
        raw[dim] = max(0.0, w + delta)

    # 归一化
    total = sum(raw.values())
    if total <= 0:
        return {dim: round(current_weights.get(dim, 0.0), 4) for dim in DIMENSIONS}
    return {dim: round(w / total, 4) for dim, w in raw.items()}


# ============ DB 函数: 跑一次校准 ============
async def _load_active_weights(db: AsyncSession) -> tuple[str, dict]:
    """读当前激活的 score_model 权重；找不到则返回默认 + 'default'"""
    from app.services.scoring import DEFAULT_WEIGHTS

    row = (await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.config_type == "score_model", ConfigVersion.is_active == True)
        .order_by(ConfigVersion.id.desc()).limit(1)
    )).scalar_one_or_none()
    if row:
        return row.version, row.definition.get("weights", DEFAULT_WEIGHTS)
    return "default", DEFAULT_WEIGHTS


async def run_calibration(
    db: AsyncSession,
    window_days: int = 30,
    end_day: _date | None = None,
) -> ModelDrift:
    """跑一次校准：取 window_days 内有销量的 listing × 它们的 ProductScore

    Returns: 已写入 DB 的 ModelDrift 行（status='generated'）
    """
    end_day = end_day or _date.today()
    start_day = end_day - timedelta(days=window_days - 1)  # 含首尾共 window_days 天
    start_str = start_day.isoformat()
    end_str = end_day.isoformat()

    model_version, current_weights = await _load_active_weights(db)

    # 取所有有销量记录的 listing × 它们的 candidate_id × ProductScore
    # join path: sales_records.listing_id → listing_drafts.id → listing_drafts.candidate_id → product_scores.candidate_id
    sales_q = (
        select(
            SalesRecord.listing_id,
            SalesRecord.date,
            SalesRecord.order_count,
            SalesRecord.refund_count,
            SalesRecord.rating,
            SalesRecord.category_rank,
            ProductScore.dimension_scores,
            ProductScore.total_score,
        )
        .join(ListingDraft, ListingDraft.id == SalesRecord.listing_id)
        .join(ProductScore, ProductScore.candidate_id == ListingDraft.candidate_id)
        .where(and_(
            SalesRecord.date >= start_str,
            SalesRecord.date <= end_str,
        ))
        .order_by(SalesRecord.listing_id, SalesRecord.date)
    )

    rows = (await db.execute(sales_q)).all()
    if not rows:
        # 零样本 — 写一条 status='generated' 但样本为 0 的记录
        drift = ModelDrift(
            model_version=model_version,
            window_start=start_str,
            window_end=end_str,
            sample_size=0,
            predicted_score_avg=None,
            realized_score_avg=None,
            calibration_error=None,
            dimension_errors_json={},
            recommended_weight_adjustments_json={},
            status="generated",
        )
        db.add(drift)
        await db.flush()
        db.add(Event(
            entity_type="model_drift",
            entity_id=_uuid4(),  # Event.entity_id 是 UUID；ModelDrift.id 是 int → 占位 UUID
            event_type="calibration_run_empty",
            actor_name="calibration_engine",
            reason=f"窗口 {start_str}..{end_str} 无销量数据",
            payload={"warning": "no_sales_in_window", "window_days": window_days, "drift_id": drift.id},
        ))
        await db.commit()
        return drift

    # 按 listing 分组
    by_listing: dict[str, list[dict]] = {}
    predicted_scores: list[float] = []
    predicted_dim_agg: dict[str, list[float]] = {d: [] for d in DIMENSIONS}
    for r in rows:
        lid = r.listing_id
        by_listing.setdefault(str(lid), []).append({
            "order_count": r.order_count,
            "refund_count": r.refund_count,
            "rating": float(r.rating) if r.rating is not None else None,
            "category_rank": r.category_rank,
        })
        if r.total_score is not None:
            predicted_scores.append(float(r.total_score))
        if r.dimension_scores:
            for d in DIMENSIONS:
                v = r.dimension_scores.get(d)
                if v is not None:
                    predicted_dim_agg[d].append(float(v))

    sample_size = len(by_listing)
    realized_per_listing = [
        {"listing_id": lid, **compute_realized_components(records)}
        for lid, records in by_listing.items()
    ]
    realized_scores = [
        compute_realized_score(by_listing[lid])
        for lid in by_listing
    ]
    realized_avg = round(sum(realized_scores) / len(realized_scores), 2) if realized_scores else None
    predicted_avg = round(sum(predicted_scores) / len(predicted_scores), 2) if predicted_scores else None
    cal_err = round(realized_avg - predicted_avg, 2) if (realized_avg is not None and predicted_avg is not None) else None

    # 维度聚合：取每个 listing 的实现分量，按维度平均后 vs 预测维度平均
    realized_components_avg = {
        d: round(sum(realized_per_listing[i][d] for i in range(len(realized_per_listing))) / len(realized_per_listing), 2)
        for d in DIMENSIONS
    } if realized_per_listing else {}
    predicted_components_avg = {
        d: round(sum(v) / len(v), 2) if v else None
        for d, v in predicted_dim_agg.items()
    }
    predicted_dim_filtered = {
        d: v for d, v in predicted_components_avg.items() if v is not None
    }
    dim_errors = dimension_errors(predicted_dim_filtered, realized_components_avg)

    # 推荐权重（仅样本充足时）
    recommended: dict = {}
    if sample_size >= MIN_SAMPLE_SIZE and predicted_dim_filtered:
        recommended = recommend_adjustments(dim_errors, current_weights)
    elif sample_size < MIN_SAMPLE_SIZE:
        # 样本不足：推荐空 dict + 警告
        recommended = {}

    drift = ModelDrift(
        model_version=model_version,
        window_start=start_str,
        window_end=end_str,
        sample_size=sample_size,
        predicted_score_avg=predicted_avg,
        realized_score_avg=realized_avg,
        calibration_error=cal_err,
        dimension_errors_json=dim_errors,
        recommended_weight_adjustments_json=recommended,
        status="generated",
    )
    db.add(drift)
    await db.flush()

    payload = {
        "sample_size": sample_size,
        "model_version": model_version,
        "window_days": window_days,
    }
    if sample_size < MIN_SAMPLE_SIZE:
        payload["warning"] = "sample_too_small"

    db.add(Event(
        entity_type="model_drift",
        entity_id=_uuid4(),  # Event.entity_id 是 UUID；ModelDrift.id 是 int → 占位 UUID
        event_type="calibration_run_completed",
        actor_name="calibration_engine",
        reason=f"校准完成：{sample_size} 样本，cal_err={cal_err}",
        payload=payload | {"drift_id": drift.id},
    ))
    await db.commit()
    return drift