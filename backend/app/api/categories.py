"""类目字典 API — W4 占位手动导入 + 查询

PRD FR-060：定期或按需同步目标站点可用类目、属性、枚举值及字段约束
W4 实现：手动 JSON/CSV 导入；V1.1 接 Temu 适配器自动同步
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import json

from app.db.session import get_db
from app.db.models import ConfigVersion, Event
from app.services.file_parser import parse_csv
from app.core.security import get_current_user, require_role

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


class CategoryImportRequest(BaseModel):
    site: str = "us"
    categories: list[dict]  # [{"category_id": "...", "name": "...", "parent_id": "...", "attrs": [...]}]


class CategorySearchRequest(BaseModel):
    keyword: str
    site: str = "us"


@router.post("/import")
async def import_categories(
    site: str = Form("us"),
    file: Optional[UploadFile] = File(None),
    body: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """手动导入类目字典（CSV 或 JSON）

    CSV 列：category_id, name, parent_id, attribute_key, attribute_type, enum_value
    JSON：{categories: [...]}
    """
    require_role(user, ["admin", "operator"])

    cats = []

    if file:
        content = await file.read()
        rows = list(parse_csv(content.decode("utf-8-sig", errors="replace")
                              if file.filename and file.filename.endswith(".csv")
                              else b""))
        # 简化：单列 category_id，name
        for r in rows:
            if r.get("category_id") and r.get("name"):
                cats.append({
                    "category_id": r["category_id"],
                    "name": r["name"],
                    "parent_id": r.get("parent_id") or None,
                    "attributes": [],
                })
    elif body:
        try:
            data = json.loads(body)
            cats = data.get("categories", [])
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"invalid JSON: {e}")
    else:
        raise HTTPException(400, "must provide file or body")

    if not cats:
        raise HTTPException(400, "no categories in input")

    # 存为 config_versions（type='category_dict'）
    version = f"{site}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    cfg = ConfigVersion(
        config_type="category_dict",
        version=version,
        definition={"site": site, "categories": cats, "count": len(cats)},
        is_active=True,
        activated_at=datetime.now(timezone.utc),
    )
    db.add(cfg)

    db.add(Event(
        entity_type="config_version", entity_id=None,
        event_type="category_dict_imported",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=f"导入 {len(cats)} 个类目 → {version}",
    ))
    await db.commit()
    return {"version": version, "count": len(cats), "site": site}


@router.post("/search")
async def search_categories(
    req: CategorySearchRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """类目关键词搜索（W4：从已导入字典查）"""
    require_role(user, ["admin", "operator", "editor", "reviewer", "readonly"])

    # 取最新激活的字典
    result = await db.execute(
        select(ConfigVersion).where(
            ConfigVersion.config_type == "category_dict",
            ConfigVersion.is_active == True,
        ).order_by(desc(ConfigVersion.id)).limit(1)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        return {"items": [], "message": "no category dict imported yet"}

    cats = cfg.definition.get("categories", [])
    site = cfg.definition.get("site", "us")

    if req.site != site:
        return {"items": [], "message": f"dict is for site '{site}', requested '{req.site}'"}

    kw = req.keyword.lower()
    matched = [c for c in cats if kw in c.get("name", "").lower() or kw in c.get("category_id", "").lower()]

    return {
        "site": site,
        "keyword": req.keyword,
        "total_in_dict": len(cats),
        "matched": len(matched),
        "items": matched[:20],
    }


@router.get("/dict")
async def get_active_dict(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """获取当前激活的字典版本"""
    require_role(user, ["admin", "operator", "editor", "reviewer", "readonly"])
    result = await db.execute(
        select(ConfigVersion).where(
            ConfigVersion.config_type == "category_dict",
            ConfigVersion.is_active == True,
        ).order_by(desc(ConfigVersion.id)).limit(1)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        return {"version": None, "categories": []}
    return {
        "version": cfg.version,
        "site": cfg.definition.get("site"),
        "count": cfg.definition.get("count"),
        "categories": cfg.definition.get("categories", []),
    }