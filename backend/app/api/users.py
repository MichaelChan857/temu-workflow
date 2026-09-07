"""用户管理 API — 列出 / 创建用户（仅管理员）"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

from app.db.session import get_db
from app.db.models import User, Shop
from app.core.security import get_current_user, require_role

router = APIRouter(prefix="/api/v1/users", tags=["users"])


VALID_ROLES = {"admin", "operator", "editor", "reviewer", "publisher", "readonly"}


class UserCreate(BaseModel):
    username: str
    display_name: str
    role: str
    password: str = "admin123"  # MVP 默认密码
    shop_id: Optional[str] = None


class UserOut(BaseModel):
    id: UUID
    username: str
    display_name: str
    role: str
    shop_id: Optional[UUID]
    is_active: bool

    class Config:
        from_attributes = True


@router.get("", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """列出用户 — 仅 admin/operator"""
    require_role(user, ["admin", "operator", "readonly"])
    result = await db.execute(select(User).order_by(User.created_at))
    return result.scalars().all()


@router.post("", response_model=UserOut)
async def create_user(req: UserCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """创建用户 — 仅 admin"""
    require_role(user, ["admin"])

    if req.role not in VALID_ROLES:
        raise HTTPException(400, f"invalid role; must be one of {VALID_ROLES}")

    # 查重
    existing = (await db.execute(
        select(User).where(User.username == req.username)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "username already exists")

    shop_uuid = None
    if req.shop_id:
        try:
            shop_uuid = UUID(req.shop_id)
        except ValueError:
            raise HTTPException(400, "invalid shop_id")

    new_user = User(
        username=req.username,
        display_name=req.display_name,
        role=req.role,
        shop_id=shop_uuid,
        encrypted_credentials={"password": req.password},
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user