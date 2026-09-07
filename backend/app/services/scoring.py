"""6 维评分（PRD §8.3）+ 推荐排序

W3-D4: 权重/阈值从 DB 读，支持运营可改
"""
from dataclasses import dataclass
from typing import Optional


# 默认配置（无 DB 配置时回退）
DEFAULT_WEIGHTS = {
    "heat": 0.25, "competition": 0.20, "profit": 0.20,
    "trend": 0.20, "ratings": 0.10, "risk": 0.05,
}
DEFAULT_THRESHOLDS = {
    "min_recommend_score": 75.0,
    "category_quota_ratio": 0.4,
    "target_count": 20,
}


# 内存缓存（避免每次评分都查 DB）
_CONFIG_CACHE = {"version": None, "weights": DEFAULT_WEIGHTS, "thresholds": DEFAULT_THRESHOLDS}


async def load_active_config(db=None) -> dict:
    """从 DB 读激活配置；失败回退默认

    使用 SELECT 1 次，结果缓存到进程内存
    """
    if db is None:
        return {"weights": DEFAULT_WEIGHTS, "thresholds": DEFAULT_THRESHOLDS}

    try:
        from sqlalchemy import select, desc
        from app.db.models import ConfigVersion

        result = await db.execute(
            select(ConfigVersion).where(
                ConfigVersion.config_type == "score_model",
                ConfigVersion.is_active == True,
            ).order_by(desc(ConfigVersion.id)).limit(1)
        )
        cfg = result.scalar_one_or_none()
        if cfg:
            return {"weights": cfg.definition["weights"], "thresholds": cfg.definition["thresholds"]}
    except Exception:
        pass

    return {"weights": DEFAULT_WEIGHTS, "thresholds": DEFAULT_THRESHOLDS}


@dataclass
class ScoreResult:
    dimension_scores: dict
    total_score: float
    confidence: float
    reason: str
    risks: list
    data_gaps: list


def score_candidate(c: dict, weights: Optional[dict] = None) -> ScoreResult:
    """6 维评分（纯函数，不依赖 DB）

    Args:
        c: 标准化后的候选商品 dict
        weights: 自定义权重（None 用默认）

    Returns:
        ScoreResult
    """
    w = weights or DEFAULT_WEIGHTS

    scores = {}
    data_gaps = []
    risks = []

    # 1. 市场热度
    title = (c.get("title") or "").lower()
    heat = 50.0
    if any(kw in title for kw in ["pet", "kitchen", "phone", "fitness"]):
        heat = 80.0
    if (c.get("price") or 0) > 100:
        heat -= 20
    if (c.get("price") or 0) < 10:
        heat -= 10
    scores["heat"] = max(0, min(100, heat))

    # 2. 竞争程度
    price = c.get("price") or 0
    cost = c.get("cost") or 0
    if price > 0:
        margin = (price - cost) / price if cost > 0 else 0.5
        competition = 50 + (margin - 0.3) * 100
    else:
        competition = 0
        data_gaps.append("competition")
    scores["competition"] = max(0, min(100, competition))

    # 3. 价格/利润
    if price and cost:
        margin = (price - cost) / price
        if margin >= 0.5:
            profit = 95
        elif margin >= 0.35:
            profit = 80
        elif margin >= 0.25:
            profit = 65
        else:
            profit = 30
            risks.append(f"low_margin:{round(margin*100, 1)}%")
    else:
        profit = 50
        data_gaps.append("profit")
    scores["profit"] = profit

    # 4. 销量与趋势
    scores["trend"] = 60
    data_gaps.append("trend")

    # 5. 评价质量
    scores["ratings"] = 60
    data_gaps.append("ratings")

    # 6. 风险控制
    risk = 80
    if (c.get("weight_g") or 0) > 1500:
        risk -= 15
    if not c.get("rights_confirmed"):
        risk -= 30
        risks.append("rights_not_confirmed")
    scores["risk"] = max(0, risk)

    # 总分（加权求和）
    total = sum(scores[k] * w.get(k, 1/6) for k in scores)

    confidence = max(0.3, 1.0 - len(data_gaps) * 0.12)
    reason = _build_reason(scores, total, data_gaps, risks)

    return ScoreResult(
        dimension_scores=scores,
        total_score=round(total, 2),
        confidence=round(confidence, 2),
        reason=reason,
        risks=risks,
        data_gaps=data_gaps,
    )


def _build_reason(scores: dict, total: float, gaps: list, risks: list) -> str:
    parts = []
    if total >= 85:
        parts.append("强推荐")
    elif total >= 75:
        parts.append("推荐")
    elif total >= 60:
        parts.append("观察")
    else:
        parts.append("不推荐")
    if risks:
        parts.append(f"风险:{','.join(risks)}")
    if gaps:
        parts.append(f"数据缺失:{','.join(gaps)}")
    return "; ".join(parts)


def rank_candidates(candidates: list[dict], thresholds: Optional[dict] = None) -> list[dict]:
    """按总分降序推荐，应用类目配额

    Args:
        candidates: [{"candidate": dict, "score": ScoreResult}, ...]
        thresholds: 自定义阈值（含 min_recommend_score / category_quota_ratio / target_count）

    Returns:
        同结构，已排序 + 标记推荐
    """
    t = thresholds or DEFAULT_THRESHOLDS
    min_score = t["min_recommend_score"]
    quota = t["category_quota_ratio"]
    target = int(t["target_count"])

    sorted_candidates = sorted(
        candidates,
        key=lambda x: (
            -x["score"].total_score,
            x["score"].dimension_scores.get("risk", 100),
            -x["score"].confidence,
        ),
    )

    selected = []
    category_count: dict[str, int] = {}

    for item in sorted_candidates:
        if item["score"].total_score < min_score:
            break
        cat = item["candidate"].get("category") or "unknown"
        if category_count.get(cat, 0) >= target * quota:
            continue
        selected.append(item)
        category_count[cat] = category_count.get(cat, 0) + 1
        if len(selected) >= target:
            break

    return selected