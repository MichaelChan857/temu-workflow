"""评分配置 API — 运营可改权重/阈值（PRD FR-032）

MVP 流程：
  1. 列出所有版本
  2. 激活版本 → 后续评分用激活版本
  3. 创建新版本（草稿）→ 预览 → 激活
  4. 每次激活写入 config_versions 表 + Event
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

from app.db.session import get_db
from app.db.models import ConfigVersion, Event
from app.core.security import get_current_user, require_role

router = APIRouter(prefix="/api/v1/scoring-config", tags=["scoring-config"])


# 默认配置（PRD §8.3）
DEFAULT_WEIGHTS = {
    "heat": 0.25,        # 市场热度
    "competition": 0.20,  # 竞争程度
    "profit": 0.20,       # 价格/利润
    "trend": 0.20,        # 销量趋势
    "ratings": 0.10,      # 评价质量
    "risk": 0.05,         # 风险控制
}
DEFAULT_THRESHOLDS = {
    "min_recommend_score": 75.0,
    "category_quota_ratio": 0.4,
    "target_count": 20,
}


class ScoringConfig(BaseModel):
    weights: dict[str, float] = Field(..., description="6 维度权重和必须 = 1.0")
    thresholds: dict[str, float] = Field(..., description="min_recommend_score / category_quota_ratio / target_count")
    name: Optional[str] = None


class ConfigVersionOut(BaseModel):
    id: int
    version: str
    definition: dict
    is_active: bool
    created_at: str
    activated_at: Optional[str]


@router.get("", response_model=list[ConfigVersionOut])
async def list_configs(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """列出所有评分配置版本（含历史）"""
    require_role(user, ["admin", "operator", "editor", "readonly"])
    result = await db.execute(
        select(ConfigVersion).where(ConfigVersion.config_type == "score_model").order_by(desc(ConfigVersion.id))
    )
    versions = result.scalars().all()
    return [
        ConfigVersionOut(
            id=v.id, version=v.version, definition=v.definition,
            is_active=v.is_active,
            created_at=v.created_at.isoformat(),
            activated_at=v.activated_at.isoformat() if v.activated_at else None,
        )
        for v in versions
    ]


@router.get("/active")
async def get_active_config(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """获取当前激活的评分配置（评分引擎用）"""
    result = await db.execute(
        select(ConfigVersion).where(
            ConfigVersion.config_type == "score_model",
            ConfigVersion.is_active == True,
        ).order_by(desc(ConfigVersion.id)).limit(1)
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        return {"version": cfg.version, **cfg.definition}
    # 默认（首次运行无激活版本）
    return {"version": "default", "weights": DEFAULT_WEIGHTS, "thresholds": DEFAULT_THRESHOLDS}


@router.post("")
async def create_config(
    req: ScoringConfig,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """创建新配置版本（草稿）"""
    require_role(user, ["admin", "operator"])

    # 校验权重和 = 1.0
    weight_sum = sum(req.weights.values())
    if abs(weight_sum - 1.0) > 0.01:
        raise HTTPException(400, f"weights sum must = 1.0, got {weight_sum:.3f}")

    # 校验必填维度
    required_dims = {"heat", "competition", "profit", "trend", "ratings", "risk"}
    missing = required_dims - set(req.weights.keys())
    if missing:
        raise HTTPException(400, f"missing dimensions: {missing}")

    # 版本号
    name = req.name or f"v{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    definition = {"weights": req.weights, "thresholds": req.thresholds}

    cfg = ConfigVersion(
        config_type="score_model",
        version=name,
        definition=definition,
        is_active=False,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)

    db.add(Event(
        entity_type="config_version", entity_id=cfg.id,
        event_type="scoring_config_created",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=f"创建评分配置 {name}",
        payload=definition,
    ))
    await db.commit()
    return {"id": cfg.id, "version": cfg.version, "definition": definition}


@router.post("/{config_id}/activate")
async def activate_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """激活指定配置版本

    PRD FR-021：规则/权重变更版本化；旧版本仍可查
    """
    require_role(user, ["admin", "operator"])

    target = await db.get(ConfigVersion, config_id)
    if not target or target.config_type != "score_model":
        raise HTTPException(404, "config not found")

    # 取消其他激活
    result = await db.execute(
        select(ConfigVersion).where(
            ConfigVersion.config_type == "score_model",
            ConfigVersion.is_active == True,
        )
    )
    for old in result.scalars().all():
        old.is_active = False

    # 激活新版本
    target.is_active = True
    target.activated_at = datetime.now(timezone.utc)

    db.add(Event(
        entity_type="config_version", entity_id=target.id,
        event_type="scoring_config_activated",
        from_status="draft", to_status="active",
        actor_id=UUID(user["id"]), actor_name=user["username"],
        reason=f"激活 {target.version}",
        payload=target.definition,
    ))
    await db.commit()
    return {"id": target.id, "version": target.version, "is_active": True}


@router.post("/reset-to-default")
async def reset_to_default(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """重置为 PRD 默认配置"""
    require_role(user, ["admin"])
    name = f"default-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    cfg = ConfigVersion(
        config_type="score_model",
        version=name,
        definition={"weights": DEFAULT_WEIGHTS, "thresholds": DEFAULT_THRESHOLDS},
        is_active=True,
        activated_at=datetime.now(timezone.utc),
    )
    db.add(cfg)
    await db.commit()
    return {"id": cfg.id, "version": cfg.version, "is_active": True}