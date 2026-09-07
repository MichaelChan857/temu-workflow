"""开发模式启动器 — 无需 Docker

不依赖 PostgreSQL / Redis，用 SQLite + 内存事件总线。
用于本地快速验证 / 演示。
"""
import os
import sys
from pathlib import Path

# 让 settings 能找到 app
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============ 切到 SQLite 模式 ============
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./temu_demo.db"
os.environ["REDIS_URL"] = "memory://"
os.environ["TEMU_USE_MOCK"] = "true"
os.environ["SECRET_KEY"] = "dev-secret-key-32-bytes-minimum-length"
os.environ["DEBUG"] = "true"
os.environ["CORS_ORIGINS"] = "http://localhost:3000,http://localhost:8000"


# ============ 修改 settings 让它支持 SQLite ============
def patch_config_for_sqlite():
    """运行时把 settings 切到 SQLite"""
    from app.core import config
    config.settings.DATABASE_URL = os.environ["DATABASE_URL"]


# ============ 修改 models 用 SQLite 兼容类型 ============
def patch_models_for_sqlite():
    """PostgreSQL 特定类型 → SQLite 兼容"""
    import sqlalchemy.dialects.postgresql as pg
    import sqlalchemy as sa

    # UUID → String（SQLite 不支持原生 UUID）
    UUID = pg.UUID
    JSONB = pg.JSONB

    # Monkey-patch: 让所有 Column(UUID(as_uuid=True)) 在 SQLite 下变 String
    original_column = sa.Column

    def patched_column(*args, **kwargs):
        # 替换 UUID → String(36)
        new_args = []
        for arg in args:
            if isinstance(arg, UUID):
                new_args.append(sa.String(36))
            elif isinstance(arg, JSONB):
                new_args.append(sa.JSON)
            else:
                new_args.append(arg)
        return original_column(*new_args, **kwargs)

    # 不动 — 改用更安全的方式：创建新 metadata
    # 实际上 aiosqlite 对 UUID(as_uuid=True) 兼容（存为字符串）


def main():
    """主入口：初始化 DB + 启动 uvicorn"""
    print("=" * 60)
    print("Temu Workflow MVP - 开发模式（SQLite，无 Docker）")
    print("=" * 60)

    patch_config_for_sqlite()

    # 导入主 app
    from app.main import app
    import uvicorn

    # 初始化 DB（SQLite 用 Base.metadata.create_all）
    import asyncio
    from app.db.base import Base
    from app.db.session import engine
    from app.db import models  # noqa

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("[OK] 数据库表已创建（SQLite）")

    asyncio.run(init())

    # 启动服务
    print("\n启动 FastAPI on http://127.0.0.1:8000")
    print("Swagger UI: http://127.0.0.1:8000/docs")
    print("\n按 Ctrl+C 停止\n")

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()