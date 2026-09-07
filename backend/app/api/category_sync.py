"""类目字典同步 API — V1.1-A2"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.db.session import get_db
from app.db.models import ConfigVersion, Event
from app.services.category_sync import diff_dicts, generate_version_label, should_auto_activate, CategoryDictDiff
from app.core.security import get_current_user, require_role

router = APIRouter(prefix="/api/v1/categories/sync", tags=["category-sync"])


class SyncRequest(BaseModel):
    site: str = "us"
    new_dict: list[dict]  # 完整的最新字典


class SyncPreviewResponse(BaseModel):
    site: str
    current_version: Optional[str]
    new_version: str
    diff: dict
    auto_activate: bool


@router.post("/preview")
async def preview_sync(req: SyncRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """预览同步 diff — 不实际写入"""
    require_role(user, ["admin", "operator"])

    # 取当前激活字典
    result = await db.execute(
        select(ConfigVersion).where(
            ConfigVersion.config_type == "category_dict",
            ConfigVersion.is_active == True,
        ).order_by(desc(ConfigVersion.id)).limit(1)
    )
    current = result.scalar_one_or_none()
    old_dict = current.definition.get("categories", []) if current else []

    diff = diff_dicts(old_dict, req.new_dict)
    new_version = generate_version_label(req.site, datetime.now(timezone.utc))

    return {
        "site": req.site,
        "current_version": current.version if current else None,
        "new_version": new_version,
        "diff": {
            "added": diff.added,
            "modified": diff.modified,
            "removed": diff.removed,
            "summary": {
                "added_count": len(diff.added),
                "modified_count": len(diff.modified),
                "removed_count": len(diff.removed),
            },
        },
        "auto_activate": should_auto_activate(diff),
    }


@router.post("/apply")
async def apply_sync(req: SyncRequest, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """应用同步 — 实际写入"""
    require_role(user, ["admin", "operator"])

    result = await db.execute(
        select(ConfigVersion).where(
            ConfigVersion.config_type == "category_dict",
            ConfigVersion.is_active == True,
        ).order_by(desc(ConfigVersion.id)).limit(1)
    )
    current = result.scalar_one_or_none()
    old_dict = current.definition.get("categories", []) if current else []

    diff = diff_dicts(old_dict, req.new_dict)
    new_version = generate_version_label(req.site, datetime.now(timezone.utc))

    # 取消旧的
    if current:
        current.is_active = False

    # 写入新的
    cfg = ConfigVersion(
        config_type="category_dict",
        version=new_version,
        definition={"site": req.site, "categories": req.new_dict, "count": len(req.new_dict)},
        is_active=True,
        activated_at=datetime.now(timezone.utc),
    )
    db.add(cfg)

    db.add(Event(
        entity_type="config_version", entity_id=None,
        event_type="category_dict_synced",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=f"同步 {req.site} 类目字典 → {new_version}",
        payload={
            "added": len(diff.added),
            "modified": len(diff.modified),
            "removed": len(diff.removed),
        },
    ))

    await db.commit()
    return {
        "status": "synced",
        "version": new_version,
        "diff": {
            "added": len(diff.added),
            "modified": len(diff.modified),
            "removed": len(diff.removed),
        },
    }