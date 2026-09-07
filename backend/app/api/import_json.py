"""JSON 入参的导入端点 — 供 n8n / 外部系统调用

与 /import/csv 不同：
- 接收 JSON 数组而非 CSV 文件
- 不做 CSV 解析（上游已标准化）
- 返回结构相同
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import hashlib

from app.db.session import get_db
from app.db.models import (
    SelectionBatch, CandidateProduct, ProductScore, FilterResult,
    Shop, CandidateStatus, BatchStatus
)
from app.services.rules import run_rules
from app.services.scoring import score_candidate, rank_candidates

router = APIRouter(prefix="/api/v1/import", tags=["import-json"])


class CandidateInput(BaseModel):
    source_product_id: str
    title: str
    description: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    price: float
    cost: Optional[float] = None
    currency: str = "USD"
    weight_g: Optional[int] = None
    dimensions: Optional[dict] = None
    image_urls: list[str] = []
    supplier_sku: str
    source_url: Optional[str] = None


class ImportJsonRequest(BaseModel):
    shop_id: Optional[str] = None
    business_date: Optional[str] = None
    candidates: list[CandidateInput]


@router.post("/json")
async def import_json(req: ImportJsonRequest, db: AsyncSession = Depends(get_db)):
    """接收 JSON 候选清单，跑通完整流程

    设计用途：
    - n8n 工作流的最后一环（HTTP Request 节点调用）
    - 内部商品库 API 推送
    - 测试 / 调试
    """
    # 找/创建店铺
    if req.shop_id:
        try:
            shop_uuid = UUID(req.shop_id)
        except ValueError:
            raise HTTPException(400, "invalid shop_id")
        shop = await db.get(Shop, shop_uuid)
        if not shop:
            raise HTTPException(404, "shop not found")
    else:
        shop = (await db.execute(select(Shop).where(Shop.is_active == True).limit(1))).scalar_one_or_none()
        if not shop:
            shop = Shop(name="Default Shop", site="us", merchant_type="full")
            db.add(shop)
            await db.flush()

    # 批次
    business_date = req.business_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    batch = (await db.execute(
        select(SelectionBatch).where(
            SelectionBatch.shop_id == shop.id,
            SelectionBatch.business_date == business_date,
            SelectionBatch.batch_type == "daily",
            SelectionBatch.status != BatchStatus.CANCELLED,
        )
    )).scalar_one_or_none()
    if not batch:
        batch = SelectionBatch(
            shop_id=shop.id, business_date=business_date,
            batch_type="daily", target_count=20, status=BatchStatus.RUNNING,
        )
        db.add(batch)
        await db.flush()

    # 写入候选 + 规则 + 评分
    inserted = []
    scored_items = []
    filtered_count = 0
    for c_in in req.candidates:
        dedupe_parts = [c_in.supplier_sku, c_in.source_product_id, (c_in.title or "")[:50]]
        dedupe_key = hashlib.md5("|".join(dedupe_parts).encode()).hexdigest()

        # 同批次去重
        existing = (await db.execute(
            select(CandidateProduct).where(
                CandidateProduct.batch_id == batch.id,
                CandidateProduct.dedupe_key == dedupe_key,
            )
        )).scalar_one_or_none()
        if existing:
            continue

        c = CandidateProduct(
            batch_id=batch.id,
            source_product_id=c_in.source_product_id,
            source_url=c_in.source_url,
            title=c_in.title, description=c_in.description,
            brand=c_in.brand, category=c_in.category,
            price=c_in.price, cost=c_in.cost, currency=c_in.currency,
            weight_g=c_in.weight_g, dimensions=c_in.dimensions,
            image_urls=c_in.image_urls, supplier_sku=c_in.supplier_sku,
            dedupe_key=dedupe_key, status=CandidateStatus.IMPORTED,
        )
        db.add(c)
        inserted.append(c)

    await db.flush()

    # 规则 + 评分
    for c in inserted:
        c_dict = {
            "title": c.title, "description": c.description, "category": c.category,
            "price": float(c.price) if c.price else None,
            "cost": float(c.cost) if c.cost else None,
            "weight_g": c.weight_g, "dimensions": c.dimensions,
            "image_urls": c.image_urls or [], "supplier_sku": c.supplier_sku,
            "rights_confirmed": c.rights_confirmed,
        }
        passes, hits = run_rules(c_dict)
        for h in hits:
            db.add(FilterResult(
                candidate_id=c.id, rule_code=h.rule_code,
                rule_version="v1.0", rule_type=h.rule_type,
                action=h.action, evidence=h.evidence,
            ))
        if not passes:
            c.status = CandidateStatus.FILTERED_OUT
            filtered_count += 1
            continue

        c.status = CandidateStatus.NORMALIZED
        score = score_candidate(c_dict)
        c.total_score = score.total_score
        c.confidence = score.confidence
        c.status = CandidateStatus.SCORED
        db.add(ProductScore(
            candidate_id=c.id, model_version="rule-v1.0",
            dimension_scores=score.dimension_scores,
            total_score=score.total_score, confidence=score.confidence,
            reason=score.reason, risks=score.risks,
            data_gaps=score.data_gaps,
        ))
        scored_items.append({"candidate": c_dict, "score": score, "candidate_id": c.id})

    # 排序
    recommended = rank_candidates(scored_items)
    recommended_ids = [item["candidate_id"] for item in recommended]
    for c in inserted:
        if c.id in recommended_ids:
            c.status = CandidateStatus.FIRST_REVIEW
        elif c.status == CandidateStatus.SCORED:
            c.status = CandidateStatus.NOT_SELECTED

    batch.statistics = {
        "imported": len(req.candidates),
        "valid": len(inserted),
        "deduped": len(req.candidates) - len(inserted),
        "filtered_out": filtered_count,
        "scored": len(scored_items),
        "recommended": len(recommended),
    }
    batch.status = BatchStatus.SUCCESS
    batch.finished_at = datetime.now(timezone.utc)

    await db.commit()
    return {
        "batch_id": str(batch.id),
        "business_date": business_date,
        **batch.statistics,
        "recommended_ids": [str(cid) for cid in recommended_ids],
    }