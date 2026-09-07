"""告警 / 通知端点 — 接收 n8n 工作流的告警和通知"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from app.db.session import get_db
from app.db.models import Event, SelectionBatch

router = APIRouter(prefix="/api/v1", tags=["alerts"])


class AlertRequest(BaseModel):
    level: str  # info / warning / error
    title: str
    message: str
    source: Optional[str] = "n8n"


class NotificationRequest(BaseModel):
    batch_id: str
    recommended_count: int


@router.post("/alerts/send")
async def send_alert(req: AlertRequest, db: AsyncSession = Depends(get_db)):
    """接收告警，记录到事件流

    MVP 阶段：只写事件流 + stdout；后续接入邮件/IM
    """
    from uuid import uuid4
    event = Event(
        entity_type="alert", entity_id=uuid4(),  # 告警无具体 entity，用随机 UUID 占位
        event_type=f"alert_{req.level}",
        actor_name="n8n",
        reason=req.title, payload={"message": req.message, "source": req.source},
    )
    db.add(event)
    await db.commit()
    print(f"[ALERT-{req.level.upper()}] {req.title}: {req.message}")
    return {"status": "logged", "level": req.level}


@router.post("/notifications/first-review-ready")
async def notify_first_review(req: NotificationRequest, db: AsyncSession = Depends(get_db)):
    """通知一审人员有新批次

    MVP 阶段：写事件流 + 简单站内消息
    """
    from uuid import uuid4
    batch = await db.get(SelectionBatch, req.batch_id) if req.batch_id else None
    event = Event(
        entity_type="batch",
        entity_id=req.batch_id if req.batch_id else uuid4(),
        event_type="first_review_ready",
        actor_name="n8n",
        reason=f"推荐 {req.recommended_count} 个商品待审核",
        payload={"recommended_count": req.recommended_count},
    )
    db.add(event)
    await db.commit()
    return {"status": "notified", "recommended_count": req.recommended_count}


@router.get("/alerts")
async def list_alerts(db: AsyncSession = Depends(get_db), limit: int = 50):
    """查看历史告警"""
    result = await db.execute(
        select(Event)
        .where(Event.event_type.like("alert_%"))
        .order_by(desc(Event.created_at))
        .limit(limit)
    )
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "level": e.event_type.replace("alert_", ""),
            "title": e.reason,
            "message": (e.payload or {}).get("message", ""),
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]