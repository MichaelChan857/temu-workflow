"""Pydantic Settings — 配置中心"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    APP_NAME: str = "Temu Workflow MVP"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-in-production-please-use-32-bytes-minimum"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 8

    # 数据库（默认 SQLite 本地开发；生产用 postgresql+asyncpg://...）
    DATABASE_URL: str = "sqlite+aiosqlite:///./temu_demo.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Temu 适配器
    TEMU_API_BASE: str = "http://localhost:8001"
    TEMU_API_KEY: str = "mock_key"
    TEMU_USE_MOCK: bool = True

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5678"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()