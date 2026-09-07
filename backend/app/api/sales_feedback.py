"""V2.0 销量反馈 API（PRD §19）

- POST /sales-feedback/collect          admin/operator — 拉取 mock 销量（按日期）
- POST /sales-feedback/upload-csv       admin/operator — 客户 CSV 回传
- GET  /sales-feedback/records          readonly+     — 查询历史销量
"""
from __future__ import annotations

from datetime import date as _date
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_role
from app.db.session import get_db
from app.services.feedback_collector import (
    collect_for_day,
    collect_from_csv,
    query_records,
)

router = APIRouter(prefix="/api/v1/sales-feedback", tags=["sales-feedback"])


class CollectResponse(BaseModel):
    day: str
    inserted: int
    source: str


class UploadCSVResponse(BaseModel):
    inserted: int
    errors: list[dict]


class SalesRecordOut(BaseModel):
    id: int
    listing_id: str
    platform_product_id: str | None
    date: str
    order_count: int
    refund_count: int
    rating: float | None
    category_rank: int | None
    source: str

    class Config:
        from_attributes = True


@router.post("/collect", response_model=CollectResponse)
async def collect(
    day: str = Query(..., description="YYYY-MM-DD，北京时间"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """拉取 mock 销量（指定日期）"""
    require_role(user, ["admin", "operator"])
    try:
        d = _date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, f"day 格式错误：{day}（应为 YYYY-MM-DD）")

    inserted = await collect_for_day(db, d)
    from app.services.feedback_sources import get_source
    return CollectResponse(day=day, inserted=inserted, source=get_source().name)


@router.post("/upload-csv", response_model=UploadCSVResponse)
async def upload_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """客户回传 CSV 上传

    CSV 列：listing_id, date, order_count, refund_count(可选), rating(可选), category_rank(可选)
    """
    require_role(user, ["admin", "operator"])
    content = await file.read()
    if not content:
        raise HTTPException(400, "空文件")

    result = await collect_from_csv(db, content)
    return UploadCSVResponse(**result)


@router.get("/records", response_model=list[SalesRecordOut])
async def list_records(
    listing_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """查询销量记录"""
    require_role(user, ["admin", "operator", "editor", "reviewer", "readonly"])
    lid = UUID(listing_id) if listing_id else None
    rows = await query_records(db, listing_id=lid, date_from=date_from, date_to=date_to, limit=limit)
    return rows