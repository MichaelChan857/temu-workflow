"""数据库种子 — 创建 6 个角色测试用户

用法（容器内）：
    docker compose exec backend python scripts/seed_users.py
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import uuid
from sqlalchemy import select
from app.db.session import AsyncSessionLocal, init_db
from app.db.models import User, Shop


async def main():
    await init_db()
    async with AsyncSessionLocal() as db:
        # 默认店铺
        shop = (await db.execute(select(Shop).limit(1))).scalar_one_or_none()
        if not shop:
            shop = Shop(name="Default Shop", site="us", merchant_type="full")
            db.add(shop)
            await db.flush()

        users = [
            ("admin", "系统管理员", "admin"),
            ("operator", "张运营", "operator"),
            ("editor", "李编辑", "editor"),
            ("reviewer", "王审核", "reviewer"),
            ("publisher", "赵发布", "publisher"),
            ("readonly", "孙验收", "readonly"),
        ]

        for username, display_name, role in users:
            existing = (await db.execute(
                select(User).where(User.username == username)
            )).scalar_one_or_none()
            if existing:
                print(f"  [SKIP] 用户 {username} 已存在")
                continue

            user = User(
                username=username,
                display_name=display_name,
                role=role,
                shop_id=shop.id,
                is_active=True,
            )
            # 直接 set 避免 declarative __init__ 类型检查
            user.encrypted_credentials = {"password": "admin123"}
            db.add(user)
            print(f"  [OK] 创建用户 {username} ({display_name}) - {role}")

        await db.commit()
        print("\n[OK] 种子完成。默认密码均为 admin123")


if __name__ == "__main__":
    asyncio.run(main())