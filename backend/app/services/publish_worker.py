"""发布 Worker — 消费 publish_jobs → 调适配器 → 异步轮询 → 错误分类 → 重试

W5-D5：核心编排逻辑

PRD FR-085/086/087/088/089：
- 同步成功/失败/异步受理 三态分发
- 异步任务轮询直到终态
- 错误分类：retryable / fatal / need_auth / need_fix
- 自动重试（最多 3 次，指数退避）
- 同一发布意图复用幂等键

MVP 实现：
- in-process 异步任务（asyncio）
- 生产环境替换为 Celery / RQ
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    PublishJob, ListingDraft, PublishStatus, CandidateStatus, Event, Shop
)
from app.adapters.temu_client import temu_client
from app.services.retry import RetryPolicy, with_retry

log = logging.getLogger(__name__)

POLICY = RetryPolicy(
    max_attempts=int(os.getenv("PUBLISH_MAX_ATTEMPTS", "3")),
    base_delay_sec=1.0,
    max_delay_sec=30.0,
)


# ============ 单个 job 处理 ============
async def process_publish_job(db: AsyncSession, job_id: str) -> dict:
    """处理单个发布任务 — 含重试 + 异步轮询"""
    job = await db.get(PublishJob, job_id)
    if not job:
        return {"status": "not_found"}

    if job.status in (PublishStatus.PUBLISHED,):
        return {"status": "already_published", "platform_product_id": job.platform_product_id}

    listing = await db.get(ListingDraft, job.listing_id)
    if not listing:
        job.last_error = "listing not found"
        await db.commit()
        return {"status": "no_listing"}

    shop = await db.get(Shop, job.shop_id)
    if not shop:
        job.last_error = "shop not found"
        await db.commit()
        return {"status": "no_shop"}

    # 构造请求
    snap = listing.publish_snapshot or {}

    async def do_publish():
        """单次发布尝试 — 返回 (error_class, result)"""
        try:
            resp = await temu_client.publish_product(
                idempotency_key=job.idempotency_key,
                shop_id=str(shop.id),
                listing_snapshot=snap,
            )
            if resp["success"]:
                return "success", resp
            return resp.get("error_class", "fatal"), resp
        except Exception as e:
            return "retryable", {"error_class": "retryable", "error_message": str(e)}

    # 调适配器 + 自动重试
    success, result, meta = await with_retry(
        do_publish,
        policy=POLICY,
        on_retry=lambda attempt, delay, ec: log.info(
            f"job {job.id[:8]} attempt={attempt} delay={delay:.1f}s class={ec}"
        ),
    )

    # 记录 attempt
    job.attempt_count += 1
    job.attempts.append({
        "attempt_no": job.attempt_count,
        "ts": datetime.now(timezone.utc).isoformat(),
        "error_class": meta["final_error_class"],
        "delays_before": meta["delays"],
    })

    if not success:
        job.last_error_class = meta["final_error_class"]
        job.last_error = (result or {}).get("error_message", "")
        job.status = PublishStatus.FAILED

        await db.commit()
        log.warning(f"job {job.id[:8]} failed: class={job.last_error_class} msg={job.last_error}")
        return {
            "status": "failed",
            "error_class": job.last_error_class,
            "attempts": job.attempt_count,
        }

    # === 成功 — 检查是否需要异步轮询 ===
    resp = result
    if resp.get("is_async") and resp.get("platform_task_id"):
        # 异步任务：转入轮询
        job.platform_task_id = resp["platform_task_id"]
        job.platform_request_id = resp.get("platform_request_id")
        job.platform_status = "submitted"
        job.status = PublishStatus.SUBMITTED
        job.submitted_at = datetime.now(timezone.utc)
        await db.commit()

        # 异步轮询（W5-D4）
        final = await poll_until_terminal(job.id, max_polls=10, poll_interval=2.0)
        return final

    # 同步成功
    if resp.get("platform_product_id"):
        job.platform_product_id = resp["platform_product_id"]
        job.platform_task_id = resp.get("platform_task_id")
        job.platform_request_id = resp.get("platform_request_id")
        job.platform_status = resp.get("platform_status", "published")
        job.status = PublishStatus.PUBLISHED
        job.published_at = datetime.now(timezone.utc)

        # 更新 listing 状态
        listing.status = CandidateStatus.PUBLISHED

        await db.commit()
        return {"status": "published", "platform_product_id": job.platform_product_id}

    # 其他情况
    job.last_error = "unknown response"
    job.status = PublishStatus.FAILED
    await db.commit()
    return {"status": "failed", "error": "unknown"}


# ============ 异步轮询（W5-D4）============
async def poll_until_terminal(
    job_id: str,
    max_polls: int = 10,
    poll_interval: float = 2.0,
) -> dict:
    """异步任务轮询 — 最多 N 次，每次间隔 N 秒
    终态：published / publish_failed / platform_review_failed
    """
    from app.db.session import AsyncSessionLocal

    for poll_no in range(1, max_polls + 1):
        await asyncio.sleep(poll_interval)

        async with AsyncSessionLocal() as db:
            job = await db.get(PublishJob, job_id)
            if not job:
                return {"status": "not_found"}
            if not job.platform_task_id:
                return {"status": "no_task_id"}

            try:
                resp = await temu_client.query_product(
                    platform_task_id=job.platform_task_id,
                    platform_product_id=job.platform_product_id,
                )
            except Exception as e:
                log.warning(f"poll #{poll_no} failed: {e}")
                continue

            ps = resp.get("platform_status")
            log.info(f"job {job_id[:8]} poll #{poll_no} status={ps}")

            if ps in ("published", "publish_failed", "platform_review_failed", "platform_error"):
                # 终态
                job.platform_status = ps
                if ps == "published":
                    job.platform_product_id = resp.get("platform_product_id") or job.platform_product_id
                    job.status = PublishStatus.PUBLISHED
                    job.published_at = datetime.now(timezone.utc)

                    # 更新 listing
                    listing = await db.get(ListingDraft, job.listing_id)
                    if listing:
                        listing.status = CandidateStatus.PUBLISHED
                else:
                    job.status = PublishStatus.FAILED
                    job.last_error = f"platform {ps}"

                db.add(Event(
                    entity_type="publish_job", entity_id=job.id,
                    event_type=f"poll_terminal_{ps}",
                    actor_name="worker",
                    reason=f"polled {poll_no} times",
                ))
                await db.commit()
                return {"status": "terminal", "platform_status": ps, "polls": poll_no}

            # 非终态，继续轮询
            job.platform_status = ps
            await db.commit()

    # 超时：标记为 PENDING（运营可手动重试）
    async with AsyncSessionLocal() as db:
        job = await db.get(PublishJob, job_id)
        if job:
            job.last_error = f"async poll timeout after {max_polls} attempts"
            job.last_error_class = "retryable"
            await db.commit()
    return {"status": "poll_timeout", "polls": max_polls}


# ============ Worker 入口（开发用）============
async def run_worker_loop(db: AsyncSession, poll_interval: float = 5.0):
    """Worker 主循环 — 处理所有 PENDING 的 job

    生产环境用 Celery；MVP 用 asyncio 循环
    """
    while True:
        try:
            result = await db.execute(
                select(PublishJob).where(PublishJob.status == PublishStatus.PENDING).limit(10)
            )
            jobs = result.scalars().all()
            for job in jobs:
                log.info(f"processing job {job.id[:8]} attempt={job.attempt_count}")
                await process_publish_job(db, str(job.id))
        except Exception as e:
            log.exception(f"worker loop error: {e}")

        await asyncio.sleep(poll_interval)