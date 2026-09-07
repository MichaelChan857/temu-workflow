"""异步数据库会话"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings
from app.db.base import Base


def _build_engine_kwargs(url: str) -> dict:
    """SQLite 不支持连接池参数；PG/其他用 pool_size=10, max_overflow=20"""
    if url.startswith("sqlite"):
        return {"echo": False}
    return {"echo": False, "pool_size": 10, "max_overflow": 20}


engine = create_async_engine(
    settings.DATABASE_URL,
    **_build_engine_kwargs(settings.DATABASE_URL),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """开发环境直接 create_all；生产用 Alembic"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)