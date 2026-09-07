"""V2.0 销量反馈采集器（PRD §19）

- collect_for_day(day)  → 拉取当天所有已发布 listing 的销量
- collect_from_csv(content) → 解析客户回传 CSV，upsert

幂等保证：sales_records 有 (listing_id, date, source) unique 约束。
重跑 collect_for_day 不会产生重复行。
"""
from __future__ import annotations

from datetime import date as _date
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # type: ignore
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ListingDraft,
    PublishJob,
    PublishStatus,
    SalesRecord,
)
from app.services.feedback_sources import get_source


# ============ 平台商品 ID 解析 ============
async def _published_listings_with_platform_id(db: AsyncSession) -> list[tuple[UUID, str]]:
    """返回 [(listing_id, platform_product_id)]

    join: publish_jobs WHERE status=published → listing_drafts
    """
    rows = await db.execute(
        select(PublishJob.listing_id, PublishJob.platform_product_id)
        .where(PublishJob.status == PublishStatus.PUBLISHED)
        .where(PublishJob.platform_product_id.is_not(None))
    )
    return [(r[0], r[1]) for r in rows.all()]


# ============ Mock 拉取 ============
async def collect_for_day(db: AsyncSession, day: _date) -> int:
    """拉取 day 当天销量（mock 或 temu_api）

    Returns: 新增/更新的行数
    """
    source = get_source()
    listings = await _published_listings_with_platform_id(db)
    if not listings:
        return 0

    pids = [pid for _, pid in listings]
    raws = await source.fetch(day, pids)

    pid_to_listing = {pid: lid for lid, pid in listings}
    rows = [
        {
            "listing_id": pid_to_listing[r.platform_product_id],
            "platform_product_id": r.platform_product_id,
            "date": r.date,
            "order_count": r.order_count,
            "refund_count": r.refund_count,
            "rating": r.rating,
            "category_rank": r.category_rank,
            "source": source.name,
            "raw_payload": None,
        }
        for r in raws
    ]
    return await _upsert(db, rows)


# ============ CSV 客户回传 ============
REQUIRED_COLUMNS = {"listing_id", "date", "order_count"}
OPTIONAL_COLUMNS = {"refund_count", "rating", "category_rank"}


async def collect_from_csv(db: AsyncSession, content: bytes) -> dict:
    """解析 CSV 并 upsert

    Returns: {"inserted": int, "errors": list[dict]}
    """
    from app.services.file_parser import parse_csv

    errors: list[dict] = []
    rows_to_insert: list[dict] = []

    for i, raw in enumerate(parse_csv(content), start=1):
        missing = REQUIRED_COLUMNS - raw.keys()
        if missing:
            errors.append({"row": i, "error": f"missing columns: {sorted(missing)}"})
            continue

        try:
            listing_uuid = UUID(raw["listing_id"])
        except (ValueError, KeyError):
            errors.append({"row": i, "error": f"invalid listing_id: {raw.get('listing_id')}"})
            continue

        rows_to_insert.append({
            "listing_id": listing_uuid,
            "platform_product_id": None,
            "date": raw["date"],
            "order_count": int(raw["order_count"]),
            "refund_count": int(raw.get("refund_count") or 0),
            "rating": float(raw["rating"]) if raw.get("rating") else None,
            "category_rank": int(raw["category_rank"]) if raw.get("category_rank") else None,
            "source": "csv",
            "raw_payload": None,
        })

    inserted = await _upsert(db, rows_to_insert)
    return {"inserted": inserted, "errors": errors}


# ============ 通用 upsert（SQLite ON CONFLICT DO UPDATE）============
async def _upsert(db: AsyncSession, rows: list[dict]) -> int:
    """按 (listing_id, date, source) upsert

    SQLite 没有原生 ON CONFLICT，但 SQLAlchemy 提供 sqlite_insert(...).on_conflict_do_update()
    PG 用同样的语义需要换 dialect — 这里仅在 SQLite 模式有效（与 V1.1 一致）。
    """
    if not rows:
        return 0
    stmt = sqlite_insert(SalesRecord).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["listing_id", "date", "source"],
        set_={
            "order_count": stmt.excluded.order_count,
            "refund_count": stmt.excluded.refund_count,
            "rating": stmt.excluded.rating,
            "category_rank": stmt.excluded.category_rank,
            "raw_payload": stmt.excluded.raw_payload,
        },
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or len(rows)


# ============ 查询 ============
async def query_records(
    db: AsyncSession,
    listing_id: UUID | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
) -> list[SalesRecord]:
    stmt = select(SalesRecord).order_by(SalesRecord.date.desc()).limit(limit)
    if listing_id:
        stmt = stmt.where(SalesRecord.listing_id == listing_id)
    if date_from:
        stmt = stmt.where(SalesRecord.date >= date_from)
    if date_to:
        stmt = stmt.where(SalesRecord.date <= date_to)
    rows = await db.execute(stmt)
    return list(rows.scalars().all())