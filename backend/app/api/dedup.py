"""V2.0 重复商品检测 API（PRD FR-021）

- GET /api/v1/dedup/check?listing_id=  → admin/operator/reviewer，返回 dup hit 列表

二审钩子在 listings.py 内联调用 find_duplicates() — 不经此端点。
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_role
from app.db.models import ListingDraft
from app.db.session import get_db
from app.services.similarity import find_duplicates

router = APIRouter(prefix="/api/v1/dedup", tags=["dedup"])


class DuplicateHitOut(BaseModel):
    listing_id: str
    title: str
    image_similarity: float
    text_similarity: float
    similarity: float


class DedupCheckResponse(BaseModel):
    listing_id: str
    duplicates: list[DuplicateHitOut]


@router.get("/check", response_model=DedupCheckResponse)
async def check(
    listing_id: str = Query(...),
    threshold: float = Query(0.95, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """检查 listing 在同 shop 是否重复"""
    require_role(user, ["admin", "operator", "reviewer"])
    listing = await db.get(ListingDraft, UUID(listing_id))
    if not listing:
        raise HTTPException(404, "listing not found")

    hits = await find_duplicates(
        db,
        shop_id=listing.shop_id,
        exclude_listing_id=listing.id,
        image_urls=listing.image_urls or [],
        title=listing.title or "",
        threshold=threshold,
    )
    return DedupCheckResponse(
        listing_id=str(listing.id),
        duplicates=[DuplicateHitOut(**h) for h in hits],
    )