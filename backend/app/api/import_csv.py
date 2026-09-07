"""文件导入 — 支持 CSV / XLSX（MVP 必做）

W3-D1: 复用 parse_file 解析器
W3-D2: 接入 data_sources 连接器
"""
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Annotated
import hashlib
import uuid

from app.db.session import get_db
from app.db.models import (
    SelectionBatch, CandidateProduct, ProductScore, FilterResult,
    DataSource, Shop, CandidateStatus, BatchStatus
)
from app.services.rules import run_rules
from app.services.scoring import score_candidate, rank_candidates
from app.services.file_parser import parse_file
from app.core.security import get_current_user, require_permission

router = APIRouter(prefix="/api/v1/import", tags=["import"])


# CSV 列定义（CSV / XLSX 共用）
FILE_COLUMNS = [
    "source_product_id", "title", "description", "brand", "category",
    "price", "cost", "currency", "weight_g", "length_cm", "width_cm", "height_cm",
    "image_url_1", "image_url_2", "image_url_3", "supplier_sku", "source_url",
]
REQUIRED_FIELDS = ["source_product_id", "title", "price", "supplier_sku", "image_url_1"]


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))  # 兼容 "300.0" 这种
    except (ValueError, TypeError):
        return None


def _normalize_row(row: dict) -> dict:
    """标准化单行 — PRD FR-014"""
    row["price"] = _to_float(row.get("price"))
    row["cost"] = _to_float(row.get("cost"))
    row["weight_g"] = _to_int(row.get("weight_g"))

    # 尺寸
    dims = {}
    for k_in, k_out in [("length_cm", "l"), ("width_cm", "w"), ("height_cm", "h")]:
        v = _to_float(row.get(k_in))
        if v is not None:
            dims[k_out] = v
    if dims:
        row["dimensions"] = dims

    # 图片
    images = [row.get(f"image_url_{i}") for i in (1, 2, 3) if row.get(f"image_url_{i}")]
    row["image_urls"] = images

    # 去重 key（PRD FR-015）
    parts = [row.get("supplier_sku", ""), row.get("source_product_id", ""), (row.get("title") or "")[:50]]
    row["dedupe_key"] = hashlib.md5("|".join(parts).encode()).hexdigest()

    return row


def _validate_row(row: dict, line_no: int) -> str | None:
    """模板校验，返回错误信息（None 表示通过）"""
    for field in REQUIRED_FIELDS:
        if not row.get(field):
            return f"Line {line_no}: missing required field '{field}'"
    if row.get("price") is None:
        return f"Line {line_no}: invalid price"
    return None


@router.post("/file")
async def import_file(
    file: Annotated[UploadFile, File(description="CSV 或 XLSX 文件")],
    shop_id: Annotated[str, Form()] = "default",
    data_source_id: Annotated[str | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """导入文件（CSV / XLSX）并跑通完整选品流程

    Returns:
        {
            batch_id, business_date,
            imported / errors / valid / deduped / filtered_out / scored / recommended,
            recommended_ids,
        }
    """
    require_permission(user, "batches")

    # 1. 读 + 解析
    content = await file.read()
    try:
        rows = list(parse_file(file.filename or "input.csv", content))
    except ValueError as e:
        raise HTTPException(400, str(e))

    # 3. 校验 + 标准化
    errors = []
    normalized_rows = []
    for i, row in enumerate(rows, start=2):
        err = _validate_row(row, i)
        if err:
            errors.append({"line": i, "error": err})
        else:
            normalized_rows.append(_normalize_row(row))

    # 4. 找店铺
    if shop_id != "default":
        try:
            shop_uuid = uuid.UUID(shop_id)
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

    # 5. 数据源（PRD FR-012）
    source = None
    if data_source_id:
        try:
            source_uuid = uuid.UUID(data_source_id)
            source = await db.get(DataSource, source_uuid)
        except ValueError:
            pass

    # 6. 批次（防重复 — PRD AC-01）
    business_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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

    # 7. 写候选 + 去重
    seen = set()
    deduped = 0
    inserted = []
    for r in normalized_rows:
        if r["dedupe_key"] in seen:
            deduped += 1
            continue
        seen.add(r["dedupe_key"])
        existing = (await db.execute(
            select(CandidateProduct).where(
                CandidateProduct.batch_id == batch.id,
                CandidateProduct.dedupe_key == r["dedupe_key"],
            )
        )).scalar_one_or_none()
        if existing:
            deduped += 1
            continue

        c = CandidateProduct(
            batch_id=batch.id, source_id=source.id if source else None,
            source_product_id=r.get("source_product_id", ""),
            source_url=r.get("source_url"),
            title=r["title"], description=r.get("description"),
            brand=r.get("brand"), category=r.get("category"),
            price=r["price"], cost=r.get("cost"),
            currency=r.get("currency") or "USD",
            weight_g=r.get("weight_g"), dimensions=r.get("dimensions"),
            image_urls=r.get("image_urls", []),
            supplier_sku=r["supplier_sku"],
            dedupe_key=r["dedupe_key"],
            status=CandidateStatus.IMPORTED,
        )
        db.add(c)
        inserted.append(c)

    await db.flush()

    # 8. 规则 + 评分
    scored = []
    filtered = 0
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
            filtered += 1
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
            reason=score.reason, risks=score.risks, data_gaps=score.data_gaps,
        ))
        scored.append({"candidate": c_dict, "score": score, "candidate_id": c.id})

    # 9. 排序
    recommended = rank_candidates(scored)
    rec_ids = [i["candidate_id"] for i in recommended]
    for c in inserted:
        if c.id in rec_ids:
            c.status = CandidateStatus.FIRST_REVIEW
        elif c.status == CandidateStatus.SCORED:
            c.status = CandidateStatus.NOT_SELECTED

    batch.statistics = {
        "imported": len(rows),
        "errors": len(errors),
        "valid": len(normalized_rows),
        "deduped": deduped,
        "filtered_out": filtered,
        "scored": len(scored),
        "recommended": len(recommended),
    }
    batch.status = BatchStatus.SUCCESS
    batch.finished_at = datetime.now(timezone.utc)

    await db.commit()
    return {
        "batch_id": str(batch.id),
        "business_date": business_date,
        "filename": file.filename,
        "filetype": (file.filename or "").split(".")[-1].lower(),
        **batch.statistics,
        "errors": errors[:20],
        "recommended_ids": [str(cid) for cid in rec_ids],
    }


# 保留 /csv 端点（向后兼容）
@router.post("/csv")
async def import_csv_legacy(
    file: UploadFile = File(...),
    shop_id: str = "default-shop",
    db: AsyncSession = Depends(get_db),
):
    """向后兼容 — 委托给 /file"""
    # 简单复用
    from fastapi import Form
    # 注：旧端点不接受 shop_id 字符串之外的 Form，这里直接转发
    return await import_file(
        file=file,
        shop_id="default",
        data_source_id=None,
        db=db,
        user={"id": "legacy", "username": "system", "role": "admin"},  # MVP 兼容
    )