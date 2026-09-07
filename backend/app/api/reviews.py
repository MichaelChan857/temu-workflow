"""审核 API — 一审列表/详情/决策（PRD FR-040 ~ FR-045）

W2 增强：
- JWT 鉴权 + RBAC 权限
- 乐观锁（version 字段）防止并发覆盖
- 数据快照（before/after）写入 events 表
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, update
from uuid import UUID
from typing import Optional
import json

from app.db.session import get_db
from app.db.models import (
    CandidateProduct, ProductScore, ReviewTask, Event,
    CandidateStatus, ReviewStage
)
from app.schemas.schemas import (
    CandidateSummary, CandidateDetail, ReviewDecision, BatchListItem
)
from app.core.security import (
    get_current_user, require_permission, require_role
)

router = APIRouter(prefix="/api/v1", tags=["review"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/batches", response_model=list[BatchListItem])
async def list_batches(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    limit: int = 20,
):
    """批次列表 — 所有角色可见"""
    from app.db.models import SelectionBatch
    stmt = select(SelectionBatch).order_by(desc(SelectionBatch.started_at)).limit(limit)

    # 店铺数据范围隔离：非 admin 且有 shop_id → 只能看自己店铺
    if user["role"] != "admin" and user.get("shop_id"):
        stmt = stmt.where(SelectionBatch.shop_id == UUID(user["shop_id"]))

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/candidates", response_model=list[CandidateSummary])
async def list_candidates(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    status: Optional[str] = None,
    batch_id: Optional[UUID] = None,
    min_score: float = Query(0, ge=0, le=100),
    limit: int = Query(50, le=200),
):
    """候选列表 — 默认只显示一审状态"""
    require_permission(user, "candidates.view")
    stmt = select(CandidateProduct).order_by(desc(CandidateProduct.total_score))
    stmt = stmt.where(CandidateProduct.total_score >= min_score)
    if status:
        stmt = stmt.where(CandidateProduct.status == status)
    elif not status:
        stmt = stmt.where(CandidateProduct.status.in_([
            CandidateStatus.FIRST_REVIEW.value,
            CandidateStatus.SCORED.value,
            CandidateStatus.NOT_SELECTED.value,
        ]))
    if batch_id:
        stmt = stmt.where(CandidateProduct.batch_id == batch_id)
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
async def get_candidate(
    candidate_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """候选详情（含评分明细、规则命中）"""
    require_permission(user, "candidates.view")
    c = await db.get(CandidateProduct, candidate_id)
    if not c:
        raise HTTPException(404, "Candidate not found")

    score = (await db.execute(
        select(ProductScore).where(ProductScore.candidate_id == candidate_id)
    )).scalar_one_or_none()

    from app.db.models import FilterResult
    hits = (await db.execute(
        select(FilterResult).where(FilterResult.candidate_id == candidate_id)
    )).scalars().all()

    return CandidateDetail(
        id=c.id, title=c.title, category=c.category,
        price=float(c.price) if c.price else None,
        total_score=float(c.total_score) if c.total_score else None,
        confidence=float(c.confidence) if c.confidence else None,
        status=c.status.value, image_urls=c.image_urls or [],
        created_at=c.created_at,
        description=c.description, brand=c.brand,
        cost=float(c.cost) if c.cost else None,
        currency=c.currency, weight_g=c.weight_g,
        dimensions=c.dimensions, supplier_sku=c.supplier_sku,
        rights_confirmed=c.rights_confirmed,
        dimension_scores=score.dimension_scores if score else None,
        reason=score.reason if score else None,
        risks=score.risks if score else [],
        data_gaps=score.data_gaps if score else [],
        filter_hits=[{"rule_code": h.rule_code, "action": h.action, "evidence": h.evidence} for h in hits],
    )


@router.post("/candidates/{candidate_id}/decision")
async def decide_candidate(
    candidate_id: UUID,
    decision: ReviewDecision,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    expected_version: Optional[int] = Query(None, description="乐观锁版本号；不匹配则 409"),
):
    """一审决策（带乐观锁）

    PRD FR-041 / FR-044：并发审核防覆盖
    """
    require_permission(user, "reviews.first")

    c = await db.get(CandidateProduct, candidate_id)
    if not c:
        raise HTTPException(404, "Candidate not found")

    if c.status not in (CandidateStatus.FIRST_REVIEW, CandidateStatus.SCORED):
        raise HTTPException(400, f"Candidate status {c.status} not in review state")

    # PRD FR-042: 驳回/退回必须填原因
    if decision.decision in ("reject", "return") and not decision.reason_code:
        raise HTTPException(400, "rejection/return must include reason_code")

    # === 乐观锁校验 ===
    before_snapshot = {
        "status": c.status.value,
        "total_score": float(c.total_score) if c.total_score else None,
        "version": c.version,
    }
    if expected_version is not None and c.version != expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"version conflict: expected={expected_version}, current={c.version}; "
                   "another reviewer may have updated it",
        )

    # === 状态变更 ===
    now = datetime.now(timezone.utc)
    if decision.decision == "approve":
        new_status = CandidateStatus.CONTENT_GENERATING
    elif decision.decision == "reject":
        new_status = CandidateStatus.REJECTED_1
    elif decision.decision == "return":
        new_status = CandidateStatus.IMPORTED
    else:
        raise HTTPException(400, "invalid decision")

    # === CAS 更新（version +1）===
    result = await db.execute(
        update(CandidateProduct)
        .where(CandidateProduct.id == candidate_id, CandidateProduct.version == c.version)
        .values(status=new_status, version=CandidateProduct.version + 1)
        .returning(CandidateProduct.id)
    )
    if not result.scalar_one_or_none():
        # 另一个请求已经修改了 version
        raise HTTPException(409, "concurrent update detected; please retry")

    # 审核记录
    task = ReviewTask(
        candidate_id=candidate_id,
        stage=ReviewStage.FIRST,
        status=f"{decision.decision}d",
        decision_reason=decision.reason_code,
        decision_comment=decision.comment,
        snapshot_data={"before": before_snapshot, "decision": decision.model_dump()},
        assignee_id=UUID(user["id"]),
        decided_at=now,
    )
    db.add(task)

    # 事件流（审计）
    db.add(Event(
        entity_type="candidate", entity_id=candidate_id,
        event_type="first_review_decision",
        from_status=before_snapshot["status"], to_status=new_status.value,
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=decision.reason_code,
        payload={
            "decision": decision.decision,
            "before": before_snapshot,
            "after": {"status": new_status.value, "version": c.version + 1},
            "comment": decision.comment,
        },
    ))

    await db.commit()
    return {
        "status": "ok",
        "new_status": new_status.value,
        "new_version": c.version + 1,
        "actor": user["username"],
    }