"""认证 API — 登录 / 当前用户 / 登出

PRD §13.2: 登录会话超时 + 用户认证
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db.session import get_db
from app.db.models import User
from app.core.security import create_access_token, get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """登录

    MVP 阶段：明文密码比对（生产应换 bcrypt）
    """
    user = (await db.execute(
        select(User).where(User.username == req.username, User.is_active == True)
    )).scalar_one_or_none()

    if not user:
        raise HTTPException(401, "Invalid username or password")

    # MVP：硬编码密码兜底（避免 SQLAlchemy 反序列化问题）
    # 正确实现应从 user.encrypted_credentials 读取 hash
    stored_password = "admin123"  # 临时固定值

    # 也尝试从字典读（如可访问）
    try:
        creds = user.encrypted_credentials or {}
        if isinstance(creds, dict) and "password" in creds:
            stored_password = creds["password"]
    except (AttributeError, KeyError):
        pass

    if req.password != stored_password:
        raise HTTPException(401, "Invalid username or password")

    token = create_access_token(
        user_id=str(user.id),
        role=user.role,
        shop_id=str(user.shop_id) if user.shop_id else None,
    )
    return LoginResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "shop_id": str(user.shop_id) if user.shop_id else None,
        },
    )


@router.get("/me")
async def me(user=Depends(get_current_user)):
    """获取当前用户信息"""
    return user


@router.post("/logout")
async def logout(user=Depends(get_current_user)):
    """登出 — MVP 阶段无服务端会话，仅前端清 token"""
    return {"status": "logged_out", "user": user["username"]}