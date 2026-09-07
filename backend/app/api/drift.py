"""V2.0 校准 / 周报 / drift 报告 API（PRD §19）

关键约束（PRD §6.5）：apply 端点只创建 ConfigVersion 草稿，**不自动激活**。
运营必须到 /ui/config.html 手动点激活。
"""
from __future__ import annotations

from datetime import date as _date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_role
from app.db.session import get_db
from app.db.models import ConfigVersion, Event, ModelDrift
from app.services.calibration_engine import (
    run_calibration,
    DIMENSIONS,
    MIN_SAMPLE_SIZE,
)
from app.services.weekly_report import generate_weekly_report

router = APIRouter(prefix="/api/v1/drift", tags=["drift"])


class DriftReportOut(BaseModel):
    id: int
    model_version: str
    evaluated_at: str
    window_start: str
    window_end: str
    sample_size: int
    predicted_score_avg: float | None
    realized_score_avg: float | None
    calibration_error: float | None
    dimension_errors_json: dict
    recommended_weight_adjustments_json: dict
    status: str

    class Config:
        from_attributes = True


class CalibrateResponse(BaseModel):
    drift_id: int
    sample_size: int
    calibration_error: float | None


class ApplyResponse(BaseModel):
    drift_id: int
    config_id: int
    config_version: str
    message: str


@router.post("/calibrate", response_model=CalibrateResponse)
async def calibrate(
    window_days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Ad-hoc 跑一次校准（admin/operator）"""
    require_role(user, ["admin", "operator"])
    drift = await run_calibration(db, window_days=window_days)
    return CalibrateResponse(
        drift_id=drift.id,
        sample_size=drift.sample_size,
        calibration_error=float(drift.calibration_error) if drift.calibration_error is not None else None,
    )


@router.post("/weekly-report", response_model=DriftReportOut)
async def weekly_report(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """生成本周周报（admin，等同 orchestrator 周一 08:00 触发）"""
    require_role(user, ["admin"])
    drift = await generate_weekly_report(db)
    return drift


@router.get("/reports", response_model=list[DriftReportOut])
async def list_reports(
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Drift 历史（readonly+）"""
    require_role(user, ["admin", "operator", "editor", "reviewer", "readonly"])
    rows = (await db.execute(
        select(ModelDrift).order_by(desc(ModelDrift.evaluated_at)).limit(limit)
    )).scalars().all()
    return rows


@router.get("/reports/{drift_id}", response_model=DriftReportOut)
async def get_report(
    drift_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """单条 drift 详情（readonly+）"""
    require_role(user, ["admin", "operator", "editor", "reviewer", "readonly"])
    row = await db.get(ModelDrift, drift_id)
    if not row:
        raise HTTPException(404, "drift report not found")
    return row


@router.post("/reports/{drift_id}/apply", response_model=ApplyResponse)
async def apply_report(
    drift_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """应用 drift 报告的推荐权重 → 创建 ConfigVersion 草稿（is_active=False）

    关键约束（PRD §6.5）：**不自动激活**；运营需到 /ui/config.html 手动激活。
    """
    from uuid import UUID
    require_role(user, ["admin"])

    drift = await db.get(ModelDrift, drift_id)
    if not drift:
        raise HTTPException(404, "drift report not found")
    if drift.status != "generated":
        raise HTTPException(400, f"drift status={drift.status}，仅 generated 可 apply")
    if drift.sample_size < MIN_SAMPLE_SIZE:
        raise HTTPException(400, f"样本过少（{drift.sample_size} < {MIN_SAMPLE_SIZE}），无可推荐调整")
    if not drift.recommended_weight_adjustments_json:
        raise HTTPException(400, "drift 无推荐权重调整")

    rec = drift.recommended_weight_adjustments_json
    # 校验完整 + 和=1
    missing = set(DIMENSIONS) - set(rec.keys())
    if missing:
        raise HTTPException(400, f"推荐权重缺维度: {sorted(missing)}")
    weight_sum = sum(rec.values())
    if abs(weight_sum - 1.0) > 0.01:
        raise HTTPException(400, f"推荐权重和 != 1.0: {weight_sum:.3f}")

    # 创建 ConfigVersion 草稿
    version_name = f"drift-{drift.id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    definition = {
        "weights": rec,
        "thresholds": {},  # 沿用默认（drift 不改阈值）
        "source_drift_id": drift.id,
    }
    cfg = ConfigVersion(
        config_type="score_model",
        version=version_name,
        definition=definition,
        is_active=False,  # 强制草稿，不自动激活
    )
    db.add(cfg)
    await db.flush()

    # 更新 drift 状态 + 关联
    drift.status = "applied"
    drift.applied_at = datetime.now(timezone.utc)
    drift.applied_by_id = UUID(user["id"])
    drift.applied_config_id = cfg.id

    db.add(Event(
        entity_type="model_drift",
        entity_id=UUID(user["id"]),  # 用 actor_id 占位（drift.id 是 int，Event.entity_id 是 UUID）
        event_type="drift_applied",
        actor_id=UUID(user["id"]),
        actor_name=user["username"],
        reason=f"应用 drift #{drift.id} → 创建评分配置草稿 {version_name}",
        payload={"config_id": cfg.id, "config_version": version_name, "weights": rec, "drift_id": drift.id},
    ))
    await db.commit()
    return ApplyResponse(
        drift_id=drift.id,
        config_id=cfg.id,
        config_version=version_name,
        message="草稿已创建，请到 系统配置 → 评分模型 手动激活",
    )


@router.post("/reports/{drift_id}/ignore")
async def ignore_report(
    drift_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """忽略 drift 报告（admin）"""
    from uuid import UUID
    require_role(user, ["admin"])
    drift = await db.get(ModelDrift, drift_id)
    if not drift:
        raise HTTPException(404, "drift report not found")
    if drift.status != "generated":
        raise HTTPException(400, f"drift status={drift.status}，仅 generated 可 ignore")

    drift.status = "ignored"
    db.add(Event(
        entity_type="model_drift",
        entity_id=UUID(user["id"]),  # 占位（drift.id 是 int）
        event_type="drift_ignored",
        actor_id=UUID(user["id"]),
        actor_name=user["username"],
        reason=f"忽略 drift #{drift.id}",
        payload={"drift_id": drift.id},
    ))
    await db.commit()
    return {"drift_id": drift.id, "status": "ignored"}