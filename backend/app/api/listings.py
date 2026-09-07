"""Listing 资料编辑 API — AI 生成 / 人工编辑 / 版本对比 / 回退

W4-D2 / W4-D3
PRD FR-050~056：AI 生成 + 编辑 + 版本化 + 敏感词 + 图片管理
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from copy import deepcopy
import json

from app.services.similarity import find_duplicates

from app.db.session import get_db
from app.db.models import (
    CandidateProduct, ListingDraft, ListingVersion, ReviewTask,
    Event, CandidateStatus, Shop, PublishJob, PublishStatus, ConfigVersion
)
from app.services.claude_client import claude_client
from app.core.security import get_current_user, require_permission

router = APIRouter(prefix="/api/v1/listings", tags=["listings"])


# ============ 二审配置（PRD §13.2 + L19）============
# 是否强制一审二审同人隔离；MVP 默认建议（不强制）
SAME_REVIEWER_FORBIDDEN = ConfigVersion  # placeholder
# 用 config_version 存这个开关
async def _get_same_reviewer_policy(db: AsyncSession) -> str:
    """读取系统级配置：建议 / 强制 / 允许"""
    result = await db.execute(
        select(ConfigVersion).where(
            ConfigVersion.config_type == "review_policy",
            ConfigVersion.is_active == True,
        ).order_by(desc(ConfigVersion.id)).limit(1)
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        return cfg.definition.get("mode", "suggested")  # suggested / forced / allowed
    return "suggested"  # MVP 默认建议模式


# ============ 校验工具 ============
REQUIRED_FIELDS = ["title", "description", "category_id", "image_urls"]


async def validate_listing_for_second_review(listing: ListingDraft, db: AsyncSession) -> tuple[bool, list[str]]:
    """二审前校验（PRD FR-071 / FR-072）

    Returns:
        (can_pass, errors)
        - can_pass: True 表示可进入二审通过；False 表示必须阻塞
        - errors: 错误清单（用于 UI 展示）
    """
    errors = []
    warnings = []

    # 1. 必填字段
    for f in REQUIRED_FIELDS:
        v = getattr(listing, f, None)
        if not v or (isinstance(v, list) and len(v) == 0):
            errors.append(f"missing_required:{f}")

    # 2. 标题长度
    if listing.title and len(listing.title) > 200:
        errors.append(f"title_too_long:{len(listing.title)}")

    # 3. 重复发布检测（PRD FR-021 / §8.2）
    existing = (await db.execute(
        select(ListingDraft).where(
            ListingDraft.shop_id == listing.shop_id,
            ListingDraft.id != listing.id,
            ListingDraft.status.in_([
                CandidateStatus.READY_TO_PUBLISH,
                CandidateStatus.PUBLISHING,
                CandidateStatus.PUBLISHED,
            ]),
            ListingDraft.title == listing.title,
        )
    )).scalars().first()
    if existing:
        errors.append(f"duplicate_title:listing={existing.id}")

    # 3b. V2.0 — 图像+文本 embedding 重复检测（更严格）
    try:
        dupes = await find_duplicates(
            db,
            shop_id=listing.shop_id,
            exclude_listing_id=listing.id,
            image_urls=listing.image_urls or [],
            title=listing.title or "",
            threshold=0.95,
        )
        for d in dupes[:3]:
            errors.append(
                f"duplicate_embedding:listing={d['listing_id']},sim={d['similarity']:.2f}"
            )
    except Exception:
        # embedding 失败不阻塞（mock 不可用时降级）
        pass

    # 4. 图片可访问性（PRD FR-071）— MVP 阶段仅校验 URL 格式
    if listing.image_urls:
        for url in listing.image_urls:
            if not url.startswith(("http://", "https://")):
                errors.append(f"invalid_image_url:{url[:50]}")
                break

    # 5. 必填属性
    if not listing.attributes or len(listing.attributes) == 0:
        warnings.append("no_attributes")

    # 警告不阻塞，错误阻塞
    return (len(errors) == 0, errors + warnings)


# ============ Schemas ============
class ListingOut(BaseModel):
    id: UUID
    candidate_id: UUID
    shop_id: UUID
    title: Optional[str]
    bullet_points: list
    description: Optional[str]
    category_id: Optional[str]
    attributes: dict
    image_urls: list
    status: str
    version: int
    is_ai_generated: bool
    has_snapshot: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class GenerateRequest(BaseModel):
    candidate_id: UUID
    target_language: Optional[str] = None  # None → 用店铺默认


class EditRequest(BaseModel):
    title: Optional[str] = None
    bullet_points: Optional[list[str]] = None
    description: Optional[str] = None
    category_id: Optional[str] = None
    attributes: Optional[dict] = None
    image_urls: Optional[list[str]] = None
    change_note: Optional[str] = None


# ============ 列表 / 详情 ============
@router.get("", response_model=list[ListingOut])
async def list_listings(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    status: Optional[str] = None,
    limit: int = 50,
):
    """列出 listing 草稿"""
    require_permission(user, "listings.view")
    stmt = select(ListingDraft).order_by(desc(ListingDraft.updated_at)).limit(limit)
    if status:
        stmt = stmt.where(ListingDraft.status == status)
    result = await db.execute(stmt)
    items = result.scalars().all()
    return [
        ListingOut(
            id=l.id, candidate_id=l.candidate_id, shop_id=l.shop_id,
            title=l.title, bullet_points=l.bullet_points or [],
            description=l.description, category_id=l.category_id,
            attributes=l.attributes or {}, image_urls=l.image_urls or [],
            status=l.status.value, version=l.version,
            is_ai_generated=l.is_ai_generated,
            has_snapshot=l.publish_snapshot is not None,
            created_at=l.created_at.isoformat(),
            updated_at=l.updated_at.isoformat(),
        )
        for l in items
    ]


@router.get("/{listing_id}", response_model=ListingOut)
async def get_listing(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    require_permission(user, "listings.view")
    l = await db.get(ListingDraft, listing_id)
    if not l:
        raise HTTPException(404, "listing not found")
    return ListingOut(
        id=l.id, candidate_id=l.candidate_id, shop_id=l.shop_id,
        title=l.title, bullet_points=l.bullet_points or [],
        description=l.description, category_id=l.category_id,
        attributes=l.attributes or {}, image_urls=l.image_urls or [],
        status=l.status.value, version=l.version,
        is_ai_generated=l.is_ai_generated,
        has_snapshot=l.publish_snapshot is not None,
        created_at=l.created_at.isoformat(),
        updated_at=l.updated_at.isoformat(),
    )


# ============ AI 生成 ============
@router.post("/generate")
async def generate_content(
    req: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """AI 生成标题/卖点/描述

    PRD FR-050 / FR-051 / FR-052：
    - 基于已确认的源商品信息
    - 不得编造事实字段
    - 数据缺失标记"待补充"
    """
    require_permission(user, "listings.edit")

    c = await db.get(CandidateProduct, req.candidate_id)
    if not c:
        raise HTTPException(404, "candidate not found")

    # 找/创建 listing
    listing = (await db.execute(
        select(ListingDraft).where(ListingDraft.candidate_id == req.candidate_id)
    )).scalar_one_or_none()

    if not listing:
        # 取候选所属批次对应的 shop
        from app.db.models import SelectionBatch
        batch = await db.get(SelectionBatch, c.batch_id)
        if not batch:
            raise HTTPException(400, "candidate has no batch")
        listing = ListingDraft(
            candidate_id=c.id, shop_id=batch.shop_id,
            status=CandidateStatus.CONTENT_GENERATING,
        )
        db.add(listing)
        await db.flush()

    # 构造源信息（只传已确认的字段，避免 AI 幻觉）
    source = {
        "title": c.title,
        "description": c.description,
        "brand": c.brand,
        "category": c.category,
        "attributes": c.attributes or {},
    }
    # 过滤空值
    source = {k: v for k, v in source.items() if v}

    target_lang = req.target_language or "en"

    try:
        content = await claude_client.generate_listing_content(source, target_lang)
    except (RuntimeError, ValueError) as e:
        # 转人工处理（PRD FR-033 失败转人工）
        db.add(Event(
            entity_type="listing", entity_id=listing.id,
            event_type="ai_generation_failed",
            actor_id=UUID(user["id"]), actor_name=user["username"],
            reason=str(e),
        ))
        await db.commit()
        raise HTTPException(503, f"AI generation failed (transferred to human): {e}")

    # 应用 AI 输出
    listing.title = content.title
    listing.bullet_points = content.bullet_points
    listing.description = content.description
    # 继承源商品的图片和类目（AI 不应改变这些 — PRD FR-051）
    listing.image_urls = c.image_urls or []
    if not listing.category_id:
        listing.category_id = c.category  # 继承候选类目
    listing.version = listing.version + 1
    listing.is_ai_generated = True
    listing.status = CandidateStatus.EDITING

    # 记录 token/费用
    from app.db.models import ProductScore
    db.add(Event(
        entity_type="listing", entity_id=listing.id,
        event_type="ai_generated",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=f"prompt={content.prompt_version}",
        payload={
            "tokens_in": content.llm_tokens_in,
            "tokens_out": content.llm_tokens_out,
            "title": content.title[:80],
        },
    ))

    # 写版本快照
    snapshot = _snapshot_from_listing(listing)
    db.add(ListingVersion(
        listing_id=listing.id,
        version=listing.version,
        snapshot=snapshot,
        change_reason="ai_generated",
        change_note=f"prompt={content.prompt_version}",
        created_by_id=UUID(user["id"]),
        created_by_name=user["username"],
    ))

    await db.commit()
    await db.refresh(listing)
    return {
        "listing_id": str(listing.id),
        "version": listing.version,
        "title": listing.title,
        "bullet_points": listing.bullet_points,
        "description": listing.description,
        "tokens_in": content.llm_tokens_in,
        "tokens_out": content.llm_tokens_out,
    }


# ============ 人工编辑 ============
@router.put("/{listing_id}")
async def edit_listing(
    listing_id: UUID,
    req: EditRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """人工编辑 listing 字段

    PRD FR-053：人工编辑所有字段（可见可见），显示 AI 生成标记
    每次编辑 → version+1 + 快照
    """
    require_permission(user, "listings.edit")

    l = await db.get(ListingDraft, listing_id)
    if not l:
        raise HTTPException(404, "listing not found")

    if l.publish_snapshot is not None:
        raise HTTPException(400, "listing has frozen snapshot (passed second review); cannot edit")

    # 校验标题长度（PRD FR-055）
    if req.title and len(req.title) > 200:
        raise HTTPException(400, "title too long (max 200)")

    # 记录 before
    before = _snapshot_from_listing(l)

    # 应用变更
    if req.title is not None:
        l.title = req.title
    if req.bullet_points is not None:
        l.bullet_points = req.bullet_points
    if req.description is not None:
        l.description = req.description
    if req.category_id is not None:
        l.category_id = req.category_id
    if req.attributes is not None:
        l.attributes = req.attributes
    if req.image_urls is not None:
        l.image_urls = req.image_urls

    l.version = l.version + 1
    l.is_ai_generated = False

    # 写版本
    after = _snapshot_from_listing(l)
    db.add(ListingVersion(
        listing_id=l.id,
        version=l.version,
        snapshot=after,
        change_reason="human_edit",
        change_note=req.change_note,
        created_by_id=UUID(user["id"]),
        created_by_name=user["username"],
    ))

    db.add(Event(
        entity_type="listing", entity_id=l.id,
        event_type="listing_edited",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=req.change_note or "manual edit",
        payload={"before_version": l.version - 1, "after_version": l.version},
    ))

    await db.commit()
    await db.refresh(l)
    return {"listing_id": str(l.id), "version": l.version}


# ============ 版本对比 ============
@router.get("/{listing_id}/versions")
async def list_versions(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """列出 listing 的所有版本"""
    require_permission(user, "listings.view")
    l = await db.get(ListingDraft, listing_id)
    if not l:
        raise HTTPException(404, "listing not found")

    result = await db.execute(
        select(ListingVersion)
        .where(ListingVersion.listing_id == listing_id)
        .order_by(desc(ListingVersion.version))
    )
    versions = result.scalars().all()
    return [
        {
            "version": v.version,
            "change_reason": v.change_reason,
            "change_note": v.change_note,
            "created_by_name": v.created_by_name,
            "created_at": v.created_at.isoformat(),
            "is_frozen": v.is_frozen,
            "snapshot_size": len(json.dumps(v.snapshot)),
        }
        for v in versions
    ]


@router.get("/{listing_id}/diff")
async def diff_versions(
    listing_id: UUID,
    from_version: int,
    to_version: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """对比两个版本的差异"""
    require_permission(user, "listings.view")

    v_from = (await db.execute(
        select(ListingVersion).where(
            ListingVersion.listing_id == listing_id,
            ListingVersion.version == from_version,
        )
    )).scalar_one_or_none()
    v_to = (await db.execute(
        select(ListingVersion).where(
            ListingVersion.listing_id == listing_id,
            ListingVersion.version == to_version,
        )
    )).scalar_one_or_none()

    if not v_from or not v_to:
        raise HTTPException(404, f"version not found: {from_version} or {to_version}")

    diff = _compute_diff(v_from.snapshot, v_to.snapshot)
    return {
        "from_version": from_version,
        "to_version": to_version,
        "from_actor": v_from.created_by_name,
        "to_actor": v_to.created_by_name,
        "differences": diff,
    }


def _compute_diff(a: dict, b: dict) -> list[dict]:
    """字段级 diff（PRD §12.2）"""
    diffs = []
    all_keys = set(a.keys()) | set(b.keys())
    for key in all_keys:
        if key in ("version", "status"):
            continue
        av = a.get(key)
        bv = b.get(key)
        if av != bv:
            diffs.append({
                "field": key,
                "from": av,
                "to": bv,
            })
    return diffs


@router.post("/{listing_id}/rollback/{target_version}")
async def rollback_version(
    listing_id: UUID,
    target_version: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """回退到指定版本（已冻结的不可覆盖 — PRD FR-054）"""
    require_permission(user, "listings.edit")

    l = await db.get(ListingDraft, listing_id)
    if not l:
        raise HTTPException(404, "listing not found")

    # 已发布快照不可覆盖（PRD FR-074 间接约束）
    if l.publish_snapshot is not None:
        raise HTTPException(400, "listing has frozen publish snapshot; cannot rollback")

    target = (await db.execute(
        select(ListingVersion).where(
            ListingVersion.listing_id == listing_id,
            ListingVersion.version == target_version,
        )
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(404, f"target version {target_version} not found")

    if target.is_frozen:
        raise HTTPException(400, "target version is frozen")

    # 应用目标版本的 snapshot
    snap = target.snapshot
    l.title = snap.get("title")
    l.bullet_points = snap.get("bullet_points") or []
    l.description = snap.get("description")
    l.category_id = snap.get("category_id")
    l.attributes = snap.get("attributes") or {}
    l.image_urls = snap.get("image_urls") or []
    l.version = l.version + 1
    l.is_ai_generated = False

    # 写新版本（标记为 rollback）
    new_snap = _snapshot_from_listing(l)
    db.add(ListingVersion(
        listing_id=l.id, version=l.version, snapshot=new_snap,
        change_reason="rollback",
        change_note=f"rollback to v{target_version}",
        created_by_id=UUID(user["id"]),
        created_by_name=user["username"],
    ))

    db.add(Event(
        entity_type="listing", entity_id=l.id,
        event_type="listing_rollback",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=f"rollback to v{target_version}, new v{l.version}",
    ))

    await db.commit()
    return {"listing_id": str(l.id), "new_version": l.version, "rolled_back_to": target_version}


# ============ 工具 ============
def _snapshot_from_listing(l: ListingDraft) -> dict:
    return {
        "title": l.title,
        "bullet_points": l.bullet_points or [],
        "description": l.description,
        "category_id": l.category_id,
        "attributes": l.attributes or {},
        "image_urls": l.image_urls or [],
        "version": l.version,
        "status": l.status.value,
    }


# ============ 二审端点（W6-D1 / W6-D2）============
class SecondReviewRequest(BaseModel):
    decision: str  # approve / return / reject
    reason_code: Optional[str] = None
    comment: Optional[str] = None
    confirm_warnings: bool = False


@router.get("/{listing_id}/second-review")
async def second_review_page(
    listing_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """二审页加载 — 返回 listing + 校验结果 + 一审信息"""
    require_permission(user, "reviews.second")
    l = await db.get(ListingDraft, listing_id)
    if not l:
        raise HTTPException(404, "listing not found")

    can_pass, checks = await validate_listing_for_second_review(l, db)

    first_review = (await db.execute(
        select(ReviewTask)
        .where(ReviewTask.candidate_id == l.candidate_id, ReviewTask.stage == "first")
        .order_by(desc(ReviewTask.decided_at))
        .limit(1)
    )).scalar_one_or_none()

    return {
        "listing": {
            "id": str(l.id),
            "title": l.title,
            "bullet_points": l.bullet_points or [],
            "description": l.description,
            "category_id": l.category_id,
            "attributes": l.attributes or {},
            "image_urls": l.image_urls or [],
            "status": l.status.value,
            "version": l.version,
            "is_ai_generated": l.is_ai_generated,
            "has_snapshot": l.publish_snapshot is not None,
        },
        "first_review": {
            "reviewer": first_review.decision_comment if first_review else None,
            "reason_code": first_review.decision_reason if first_review else None,
            "decided_at": first_review.decided_at.isoformat() if first_review and first_review.decided_at else None,
        } if first_review else None,
        "checks": {
            "can_pass": can_pass,
            "errors": [c for c in checks if not c.startswith("no_")],
            "warnings": [c for c in checks if c.startswith("no_")],
        },
    }


@router.post("/{listing_id}/second-review")
async def second_review_decide(
    listing_id: UUID,
    req: SecondReviewRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """二审决策（PRD FR-073~075）"""
    require_permission(user, "reviews.second")

    l = await db.get(ListingDraft, listing_id)
    if not l:
        raise HTTPException(404, "listing not found")

    if l.publish_snapshot is not None:
        raise HTTPException(400, "listing already passed second review (frozen)")

    if l.status not in (CandidateStatus.EDITING, CandidateStatus.SECOND_REVIEW):
        raise HTTPException(400, f"listing status {l.status.value} not editable")

    can_pass, checks = await validate_listing_for_second_review(l, db)
    errors = [c for c in checks if not c.startswith("no_")]
    warnings = [c for c in checks if c.startswith("no_")]

    # W6-D2：同人校验
    policy = await _get_same_reviewer_policy(db)
    first_review = (await db.execute(
        select(ReviewTask)
        .where(ReviewTask.candidate_id == l.candidate_id, ReviewTask.stage == "first")
        .order_by(desc(ReviewTask.decided_at))
        .limit(1)
    )).scalar_one_or_none()

    same_person = bool(first_review and first_review.assignee_id and str(first_review.assignee_id) == user["id"])

    if req.decision == "approve":
        if errors:
            raise HTTPException(400, f"second review blocked: {errors}")

        if same_person and policy == "forced":
            raise HTTPException(403, "second review must be done by a different person (policy=forced)")

        if same_person and policy == "suggested":
            db.add(Event(
                entity_type="listing", entity_id=l.id,
                event_type="second_review_same_as_first",
                actor_id=UUID(user["id"]), actor_name=user["username"],
                reason="一审与二审同一人（policy=suggested）",
                payload={"policy": policy, "first_reviewer": str(first_review.assignee_id)},
            ))

        if warnings and not req.confirm_warnings:
            raise HTTPException(400, f"warnings need confirmation: {warnings}")

        # === 冻结快照（PRD FR-074 / L13）===
        snapshot = _snapshot_from_listing(l)
        l.publish_snapshot = snapshot
        l.snapshot_version = l.version
        l.status = CandidateStatus.READY_TO_PUBLISH

        # 标记旧 ListingVersion 为 frozen
        await db.execute(
            ListingVersion.__table__.update()
            .where(ListingVersion.listing_id == l.id)
            .values(is_frozen=True)
        )

        db.add(ReviewTask(
            candidate_id=l.candidate_id,
            listing_id=l.id,
            stage="second",
            status="approved",
            decision_reason=req.reason_code,
            decision_comment=req.comment,
            snapshot_data={"decision": req.decision, "checks": checks},
            assignee_id=UUID(user["id"]),
            decided_at=datetime.now(timezone.utc),
        ))

        db.add(Event(
            entity_type="listing", entity_id=l.id,
            event_type="second_review_approved",
            actor_id=UUID(user["id"]), actor_name=user["username"],
            reason="冻结快照，可发布",
            payload={"snapshot_version": l.snapshot_version},
        ))

        await db.commit()
        return {
            "status": "approved",
            "snapshot_version": l.snapshot_version,
            "listing_status": l.status.value,
            "next_step": "ready_to_publish",
        }

    elif req.decision == "return":
        if not req.reason_code:
            raise HTTPException(400, "return requires reason_code")

        l.status = CandidateStatus.EDITING
        # 清除旧快照（如有），让运营修改后重新二审
        l.publish_snapshot = None
        l.snapshot_version = None

        db.add(ReviewTask(
            candidate_id=l.candidate_id,
            listing_id=l.id,
            stage="second",
            status="returned",
            decision_reason=req.reason_code,
            decision_comment=req.comment,
            assignee_id=UUID(user["id"]),
            decided_at=datetime.now(timezone.utc),
        ))

        db.add(Event(
            entity_type="listing", entity_id=l.id,
            event_type="second_review_returned",
            actor_id=UUID(user["id"]), actor_name=user["username"],
            reason=req.reason_code,
        ))

        await db.commit()
        return {"status": "returned", "listing_status": l.status.value}

    elif req.decision == "reject":
        if not req.reason_code:
            raise HTTPException(400, "reject requires reason_code")

        l.status = CandidateStatus.REJECTED_2

        db.add(ReviewTask(
            candidate_id=l.candidate_id,
            listing_id=l.id,
            stage="second",
            status="rejected",
            decision_reason=req.reason_code,
            decision_comment=req.comment,
            assignee_id=UUID(user["id"]),
            decided_at=datetime.now(timezone.utc),
        ))

        db.add(Event(
            entity_type="listing", entity_id=l.id,
            event_type="second_review_rejected",
            actor_id=UUID(user["id"]), actor_name=user["username"],
            reason=req.reason_code,
        ))

        await db.commit()
        return {"status": "rejected", "listing_status": l.status.value}

    else:
        raise HTTPException(400, "invalid decision")


# ============ 批量操作（V1.1-A3）============
class BatchEditRequest(BaseModel):
    listing_ids: list[UUID]
    updates: dict  # 字段 → 新值（仅支持的字段）


class BatchSecondReviewRequest(BaseModel):
    listing_ids: list[UUID]
    decision: str  # approve / reject
    reason_code: Optional[str] = None
    confirm_warnings: bool = False


@router.post("/batch-edit")
async def batch_edit(
    req: BatchEditRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """批量编辑 listing 字段（V1.1-A3）

    PRD §19 V1.1：批量编辑、批量二审和更完善的错误修复建议
    """
    require_permission(user, "listings.edit")

    if not req.listing_ids:
        raise HTTPException(400, "no listing_ids provided")
    if len(req.listing_ids) > 100:
        raise HTTPException(400, "batch size exceeds 100")

    ALLOWED_FIELDS = {"title", "bullet_points", "description", "category_id", "attributes"}
    invalid = set(req.updates.keys()) - ALLOWED_FIELDS
    if invalid:
        raise HTTPException(400, f"invalid fields: {invalid}")

    if "title" in req.updates and len(req.updates["title"]) > 200:
        raise HTTPException(400, "title too long (max 200)")

    results = {"succeeded": [], "failed": []}

    for lid in req.listing_ids:
        try:
            l = await db.get(ListingDraft, lid)
            if not l:
                results["failed"].append({"listing_id": str(lid), "error": "not found"})
                continue
            if l.publish_snapshot is not None:
                results["failed"].append({"listing_id": str(lid), "error": "frozen snapshot"})
                continue

            before = _snapshot_from_listing(l)
            for field, value in req.updates.items():
                setattr(l, field, value)
            l.version = l.version + 1
            l.is_ai_generated = False

            db.add(ListingVersion(
                listing_id=l.id, version=l.version,
                snapshot=_snapshot_from_listing(l),
                change_reason="batch_edit",
                change_note=f"batch ({len(req.listing_ids)} items)",
                created_by_id=UUID(user["id"]),
                created_by_name=user["username"],
            ))
            results["succeeded"].append(str(lid))
        except Exception as e:
            results["failed"].append({"listing_id": str(lid), "error": str(e)})

    await db.commit()
    return {
        "total": len(req.listing_ids),
        "succeeded_count": len(results["succeeded"]),
        "failed_count": len(results["failed"]),
        "results": results,
    }


@router.post("/batch-second-review")
async def batch_second_review(
    req: BatchSecondReviewRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """批量二审（V1.1-A3）

    支持 approve / reject 两种决策
    - approve：所有 listing 校验通过 + 同人校验 + 警告确认后冻结
    - reject：统一驳回（不回退，因批量回退易错）
    """
    require_permission(user, "reviews.second")

    if not req.listing_ids:
        raise HTTPException(400, "no listing_ids provided")
    if len(req.listing_ids) > 50:
        raise HTTPException(400, "batch size exceeds 50")
    if req.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve or reject")

    if req.decision == "reject" and not req.reason_code:
        raise HTTPException(400, "reject requires reason_code")

    # 同人校验（一次检查）
    policy = await _get_same_reviewer_policy(db)
    same_person_blocked = []

    results = {"succeeded": [], "failed": []}

    for lid in req.listing_ids:
        try:
            l = await db.get(ListingDraft, lid)
            if not l:
                results["failed"].append({"listing_id": str(lid), "error": "not found"})
                continue
            if l.publish_snapshot is not None:
                results["failed"].append({"listing_id": str(lid), "error": "already frozen"})
                continue
            if l.status not in (CandidateStatus.EDITING, CandidateStatus.SECOND_REVIEW):
                results["failed"].append({"listing_id": str(lid), "error": f"status {l.status.value}"})
                continue

            # 同人校验
            first_review = (await db.execute(
                select(ReviewTask)
                .where(ReviewTask.candidate_id == l.candidate_id, ReviewTask.stage == "first")
                .order_by(desc(ReviewTask.decided_at)).limit(1)
            )).scalar_one_or_none()
            same_person = bool(first_review and first_review.assignee_id and str(first_review.assignee_id) == user["id"])

            if req.decision == "approve":
                # 校验
                can_pass, checks = await validate_listing_for_second_review(l, db)
                errors = [c for c in checks if not c.startswith("no_")]
                warnings = [c for c in checks if c.startswith("no_")]

                if errors:
                    results["failed"].append({"listing_id": str(lid), "error": f"validation: {errors}"})
                    continue
                if warnings and not req.confirm_warnings:
                    results["failed"].append({"listing_id": str(lid), "error": f"warnings: {warnings}"})
                    continue
                if same_person and policy == "forced":
                    results["failed"].append({"listing_id": str(lid), "error": "same reviewer forbidden"})
                    continue

                snapshot = _snapshot_from_listing(l)
                l.publish_snapshot = snapshot
                l.snapshot_version = l.version
                l.status = CandidateStatus.READY_TO_PUBLISH

                db.add(ReviewTask(
                    candidate_id=l.candidate_id, listing_id=l.id,
                    stage="second", status="approved",
                    decision_reason=req.reason_code,
                    assignee_id=UUID(user["id"]),
                    decided_at=datetime.now(timezone.utc),
                ))

                if same_person and policy == "suggested":
                    db.add(Event(
                        entity_type="listing", entity_id=l.id,
                        event_type="batch_second_review_same_as_first",
                        actor_id=UUID(user["id"]), actor_name=user["username"],
                        reason="同人（batch + suggested）",
                    ))

            elif req.decision == "reject":
                l.status = CandidateStatus.REJECTED_2
                db.add(ReviewTask(
                    candidate_id=l.candidate_id, listing_id=l.id,
                    stage="second", status="rejected",
                    decision_reason=req.reason_code,
                    assignee_id=UUID(user["id"]),
                    decided_at=datetime.now(timezone.utc),
                ))

            results["succeeded"].append(str(lid))

        except Exception as e:
            results["failed"].append({"listing_id": str(lid), "error": str(e)})

    db.add(Event(
        entity_type="batch", entity_id=None,
        event_type=f"batch_second_review_{req.decision}",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=f"批量 {req.decision} {len(results['succeeded'])}/{len(req.listing_ids)}",
        payload={
            "decision": req.decision,
            "succeeded_count": len(results["succeeded"]),
            "failed_count": len(results["failed"]),
        },
    ))
    await db.commit()
    return {
        "total": len(req.listing_ids),
        "succeeded_count": len(results["succeeded"]),
        "failed_count": len(results["failed"]),
        "results": results,
    }