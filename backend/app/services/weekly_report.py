"""V2.0 周报生成器（PRD §19）

每周一 08:00 跑：调 run_calibration(window_days=7)，状态 generated。
"""
from __future__ import annotations

from datetime import date as _date
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event, ModelDrift
from app.services.calibration_engine import run_calibration


async def generate_weekly_report(db: AsyncSession, end_day: _date | None = None) -> ModelDrift:
    """生成最近 7 天窗口的校准报告（不是真的"运行"周报，仅是一个 7 天窗口的校准）

    调度：每周一 08:00 北京时间（orchestrator 中配置）
    """
    drift = await run_calibration(db, window_days=7, end_day=end_day)

    # 额外打一个 weekly_drift_report_generated 事件便于审计
    from uuid import uuid4
    db.add(Event(
        entity_type="model_drift",
        entity_id=uuid4(),  # Event.entity_id 是 UUID；ModelDrift.id 是 int → 占位 UUID
        event_type="weekly_drift_report_generated",
        actor_name="weekly_report",
        reason=f"周报生成：{drift.window_start}..{drift.window_end}，样本 {drift.sample_size}",
        payload={
            "model_version": drift.model_version,
            "sample_size": drift.sample_size,
            "calibration_error": float(drift.calibration_error) if drift.calibration_error is not None else None,
            "drift_id": drift.id,
        },
    ))
    await db.commit()
    return drift