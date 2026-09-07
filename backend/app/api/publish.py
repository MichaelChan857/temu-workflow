"""发布 API — 发起 / 执行 / 查询

W5-D5：发布 API + Worker 触发
"""
from datetime import datetime, timezone
import hashlib
import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from uuid import UUID

from app.db.session import get_db, AsyncSessionLocal
from app.db.models import (
    ListingDraft, PublishJob, PublishStatus, CandidateStatus, Event
)
from app.core.security import get_current_user, require_permission
from app.services.publish_worker import process_publish_job

router = APIRouter(prefix="/api/v1/publish", tags=["publish"])


class PublishStartRequest(BaseModel):
    listing_id: UUID
    auto_execute: bool = True  # W5：默认立即触发 Worker


@router.post("/start")
async def start_publish(
    req: PublishStartRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """发起发布"""
    require_permission(user, "publish.execute")

    listing = await db.get(ListingDraft, req.listing_id)
    if not listing:
        raise HTTPException(404, "listing not found")

    if listing.status != CandidateStatus.READY_TO_PUBLISH:
        raise HTTPException(400, f"listing status {listing.status.value} not ready")

    if not listing.publish_snapshot:
        raise HTTPException(400, "no publish snapshot; must pass second review first")

    # 幂等键（PRD FR-083）
    idempotency_key = hashlib.sha256(
        f"{listing.shop_id}|{listing.snapshot_version}|{listing.id}".encode()
    ).hexdigest()[:32]

    # 防重复
    existing = (await db.execute(
        select(PublishJob).where(PublishJob.idempotency_key == idempotency_key)
    )).scalar_one_or_none()
    if existing:
        return {
            "job_id": str(existing.id),
            "idempotency_key": idempotency_key,
            "status": existing.status.value,
            "message": "already submitted (idempotent)",
            "platform_product_id": existing.platform_product_id,
        }

    # 创建 job
    job = PublishJob(
        listing_id=listing.id,
        shop_id=listing.shop_id,
        snapshot_version=listing.snapshot_version,
        idempotency_key=idempotency_key,
        status=PublishStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    db.add(Event(
        entity_type="publish_job", entity_id=job.id,
        event_type="publish_started",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=f"listing={listing.id} snapshot_v={listing.snapshot_version}",
    ))
    await db.commit()

    # 立即触发（后台异步执行）
    if req.auto_execute:
        background.add_task(_run_job, str(job.id))

    return {
        "job_id": str(job.id),
        "idempotency_key": idempotency_key,
        "status": job.status.value,
        "auto_executed": req.auto_execute,
    }


async def _run_job(job_id: str):
    """Background task wrapper — 独立 session"""
    async with AsyncSessionLocal() as db:
        try:
            await process_publish_job(db, job_id)
        except Exception as e:
            print(f"[Worker] job {job_id[:8]} crashed: {e}")


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: UUID,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """手动重试发布"""
    require_permission(user, "publish.retry")
    job = await db.get(PublishJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status == PublishStatus.PUBLISHED:
        raise HTTPException(400, "already published")
    job.status = PublishStatus.PENDING
    job.last_error = None
    await db.commit()

    background.add_task(_run_job, str(job.id))
    return {"status": "retrying", "job_id": str(job.id)}


@router.post("/jobs/{job_id}/close")
async def close_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """人工关闭（PRD FR-087：不可重试时人工处理）"""
    require_permission(user, "publish.execute")
    job = await db.get(PublishJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    job.status = PublishStatus.FAILED
    job.last_error = "manually closed"
    db.add(Event(
        entity_type="publish_job", entity_id=job.id,
        event_type="publish_closed",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason="人工关闭",
    ))
    await db.commit()
    return {"status": "closed"}


@router.get("/jobs/{job_id}")
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    job = await db.get(PublishJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "job_id": str(job.id),
        "status": job.status.value,
        "idempotency_key": job.idempotency_key,
        "platform_status": job.platform_status,
        "platform_product_id": job.platform_product_id,
        "platform_task_id": job.platform_task_id,
        "last_error": job.last_error,
        "last_error_class": job.last_error_class,
        "attempt_count": job.attempt_count,
        "attempts": job.attempts,
        "submitted_at": job.submitted_at.isoformat() if job.submitted_at else None,
        "published_at": job.published_at.isoformat() if job.published_at else None,
    }