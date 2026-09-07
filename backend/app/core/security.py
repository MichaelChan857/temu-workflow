"""JWT 工具 — 颁发 / 解析 token"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from jwt.exceptions import PyJWTError as JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings
from app.db.models import User

security = HTTPBearer(auto_error=False)


def create_access_token(user_id: str, role: str, shop_id: Optional[str] = None) -> str:
    """颁发 JWT

    Payload:
        - sub: user_id
        - role: 角色
        - shop_id: 数据范围（None 表示跨店）
        - exp / iat: 时间戳
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "shop_id": shop_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.JWT_EXPIRE_HOURS)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解析 token；失败抛 401"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """FastAPI 依赖：注入当前用户

    Returns: {"id", "username", "display_name", "role", "shop_id"}
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(credentials.credentials)
    return {
        "id": payload["sub"],
        "role": payload["role"],
        "shop_id": payload.get("shop_id"),
        "username": payload.get("username", payload["sub"]),
    }


# ============ 角色权限矩阵（PRD §5 + §13.1）============
# 6 个角色：admin / operator / editor / reviewer / publisher / readonly
ROLE_PERMISSIONS = {
    "admin": {
        "batches", "candidates", "reviews", "listings", "publish",
        "users", "shops", "configs", "audit", "alerts",
    },
    "operator": {
        # 选品运营：查看 + 一审
        "batches", "candidates.view", "reviews.first", "audit.view",
    },
    "editor": {
        # 商品编辑：查看 + 修订资料
        "candidates.view", "listings.edit", "reviews.first",
    },
    "reviewer": {
        # 上品审核员：一审 + 二审
        "candidates.view", "reviews.first", "reviews.second", "listings.view",
    },
    "publisher": {
        # 发布操作员：发起发布
        "listings.view", "publish.execute", "publish.retry",
    },
    "readonly": {
        # 只读验收
        "batches.view", "candidates.view", "listings.view", "audit.view",
    },
}


def check_permission(user: dict, permission: str) -> bool:
    """检查用户是否拥有指定权限"""
    role = user.get("role")
    if role == "admin":
        return True  # 管理员全部允许
    perms = ROLE_PERMISSIONS.get(role, set())
    return permission in perms


def require_role(user: dict, allowed_roles: list[str]) -> None:
    """要求用户必须是指定角色之一，否则 403"""
    if user.get("role") not in allowed_roles and user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"role '{user.get('role')}' not in {allowed_roles}",
        )


def require_permission(user: dict, permission: str) -> None:
    """要求用户必须拥有指定权限"""
    if not check_permission(user, permission):
        raise HTTPException(
            status_code=403,
            detail=f"role '{user.get('role')}' lacks permission '{permission}'",
        )