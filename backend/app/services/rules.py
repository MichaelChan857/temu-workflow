"""规则引擎 — 硬性淘汰 + 软性扣分

PRD §8.2: 硬性规则优先级高于评分，必须先过滤再评分
"""
from dataclasses import dataclass
from typing import Callable
import re


@dataclass
class RuleHit:
    rule_code: str
    rule_type: str  # 'hard' / 'soft'
    action: str  # 'filter_out' / 'flag'
    evidence: dict


# ============ 规则定义 ============
BANNED_KEYWORDS = ["replica", "fake", "counterfeit", "brand:", "lv ", "gucci ", "nike ", "adidas "]
PROHIBITED_CATEGORIES = ["weapons", "drugs", "firearms", "adult"]
BRAND_KEYWORDS = ["rolex", "gucci", "prada", "louis vuitton", "hermes"]


def check_banned_keyword(c: dict) -> RuleHit | None:
    """禁限售关键词 — 硬性"""
    text = (c.get("title", "") + " " + (c.get("description") or "")).lower()
    for kw in BANNED_KEYWORDS:
        if kw in text:
            return RuleHit("BANNED_KEYWORD", "hard", "filter_out", {"keyword": kw, "field": "title"})
    return None


def check_brand_infringement(c: dict) -> RuleHit | None:
    """侵权品牌词 — 硬性（无授权时）"""
    text = (c.get("title", "") + " " + (c.get("description") or "")).lower()
    for brand in BRAND_KEYWORDS:
        if brand in text and not c.get("rights_confirmed", False):
            return RuleHit("BRAND_INFRINGE", "hard", "filter_out", {"brand": brand})
    return None


def check_missing_required(c: dict) -> RuleHit | None:
    """必填缺失 — 硬性（PRD FR-023）"""
    missing = []
    if not c.get("title"):
        missing.append("title")
    if not c.get("price"):
        missing.append("price")
    if not c.get("image_urls"):
        missing.append("image_urls")
    if not c.get("supplier_sku"):
        missing.append("supplier_sku")
    if missing:
        return RuleHit("MISSING_REQUIRED", "hard", "filter_out", {"missing": missing})
    return None


def check_prohibited_category(c: dict) -> RuleHit | None:
    """类目黑名单 — 硬性"""
    cat = (c.get("category") or "").lower()
    for banned in PROHIBITED_CATEGORIES:
        if banned in cat:
            return RuleHit("PROHIBITED_CATEGORY", "hard", "filter_out", {"category": cat})
    return None


def check_price_out_of_range(c: dict) -> RuleHit | None:
    """价格区间 — 软性扣分（不在 5-200 USD 范围内）"""
    p = _to_num(c.get("price"))
    if p is None:
        return None
    if p < 5 or p > 200:
        return RuleHit("PRICE_OUT_OF_RANGE", "soft", "flag", {"price": p, "range": [5, 200]})
    return None


def check_low_margin(c: dict) -> RuleHit | None:
    """毛利低于 25% — 软性"""
    price = _to_num(c.get("price"))
    cost = _to_num(c.get("cost"))
    if not (price and cost and price > 0):
        return None
    margin = (price - cost) / price
    if margin < 0.25:
        return RuleHit("LOW_MARGIN", "soft", "flag", {"margin": round(margin, 3), "threshold": 0.25})
    return None


def _to_num(v):
    """安全转数字"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def check_oversized(c: dict) -> RuleHit | None:
    """超尺寸 — 硬性（>2kg 或 长+宽+高>90cm）"""
    w = _to_num(c.get("weight_g"))
    if w is not None and w > 2000:
        return RuleHit("OVERSIZED_WEIGHT", "hard", "filter_out", {"weight_g": w, "limit": 2000})
    dims = c.get("dimensions") or {}
    total = sum(_to_num(dims.get(k)) or 0 for k in ("l", "w", "h"))
    if total > 90:
        return RuleHit("OVERSIZED_DIM", "hard", "filter_out", {"total_cm": total, "limit": 90})
    return None


# ============ 规则注册表 ============
ALL_RULES: list[Callable[[dict], RuleHit | None]] = [
    check_banned_keyword,
    check_brand_infringement,
    check_missing_required,
    check_prohibited_category,
    check_price_out_of_range,
    check_low_margin,
    check_oversized,
]


def run_rules(candidate: dict) -> tuple[bool, list[RuleHit]]:
    """运行所有规则

    Returns:
        (passes, hits)
        - passes: True 表示通过硬性规则；False 表示被淘汰
        - hits: 触发的所有规则（含 soft）
    """
    hits: list[RuleHit] = []
    for rule in ALL_RULES:
        hit = rule(candidate)
        if hit:
            hits.append(hit)
    # 任何一个硬性命中 → 不通过
    hard_hits = [h for h in hits if h.rule_type == "hard"]
    return (len(hard_hits) == 0, hits)