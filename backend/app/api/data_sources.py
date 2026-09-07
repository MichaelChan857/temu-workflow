"""数据源管理 API — CRUD + 健康检查

PRD FR-011 / FR-012：支持内部商品库/供应商接口/合规第三方数据源连接器
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.db.session import get_db
from app.db.models import DataSource
from app.services.connectors import create_connector, CONNECTOR_TYPES
from app.core.security import get_current_user, require_role

router = APIRouter(prefix="/api/v1/data-sources", tags=["data-sources"])


class DataSourceCreate(BaseModel):
    name: str
    type: str  # csv / xlsx / internal_api / third_party
    owner: str
    authorization_note: Optional[str] = None
    config_ref: dict = {}


class DataSourceOut(BaseModel):
    id: UUID
    name: str
    type: str
    owner: str
    authorization_note: Optional[str]
    is_active: bool
    config_ref: Optional[dict]
    created_at: str

    class Config:
        from_attributes = True


@router.get("", response_model=list[DataSourceOut])
async def list_data_sources(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """列出所有数据源 — admin/operator/editor 可看"""
    require_role(user, ["admin", "operator", "editor", "readonly"])
    result = await db.execute(select(DataSource).order_by(DataSource.created_at))
    sources = result.scalars().all()
    return [
        DataSourceOut(
            id=s.id, name=s.name, type=s.type, owner=s.owner,
            authorization_note=s.authorization_note, is_active=s.is_active,
            config_ref=s.config_ref, created_at=s.created_at.isoformat(),
        )
        for s in sources
    ]


@router.post("", response_model=DataSourceOut)
async def create_data_source(
    req: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """创建数据源 — 仅 admin"""
    require_role(user, ["admin"])

    if req.type not in CONNECTOR_TYPES:
        raise HTTPException(400, f"unknown type; must be one of {list(CONNECTOR_TYPES)}")

    # PRD FR-017：数据源配置须记录责任人
    if not req.owner:
        raise HTTPException(400, "owner required (PRD FR-017)")

    ds = DataSource(
        name=req.name, type=req.type, owner=req.owner,
        authorization_note=req.authorization_note,
        config_ref=req.config_ref, is_active=True,
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    return DataSourceOut(
        id=ds.id, name=ds.name, type=ds.type, owner=ds.owner,
        authorization_note=ds.authorization_note, is_active=ds.is_active,
        config_ref=ds.config_ref, created_at=ds.created_at.isoformat(),
    )


@router.get("/types")
async def list_types(user=Depends(get_current_user)):
    """列出支持的连接器类型（前端下拉用）"""
    return {
        "types": list(CONNECTOR_TYPES.keys()) + ["http_api"],
        "configs": {
            "csv":     ["file_path"],
            "xlsx":    ["file_path"],
            "internal_api": ["api_url", "api_key"],
            "third_party":  ["api_url", "vendor"],
            "http_api": [
                "url", "method", "auth_type", "auth_token",
                "pagination_type", "items_path", "mapping",
            ],
        },
    }


@router.get("/{source_id}/health")
async def health_check(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """检查数据源是否可用"""
    require_role(user, ["admin", "operator"])
    ds = await db.get(DataSource, source_id)
    if not ds:
        raise HTTPException(404, "data source not found")
    try:
        connector = create_connector(ds)
        ok = connector.health_check()
        return {"data_source_id": str(ds.id), "healthy": ok, "type": ds.type}
    except Exception as e:
        return {"data_source_id": str(ds.id), "healthy": False, "error": str(e)}