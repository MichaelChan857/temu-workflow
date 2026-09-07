"""Alembic 配置 — MVP 阶段直接用 SQLAlchemy create_all 也行，但 alembic 更稳"""
from logging.config import fileConfig
import os
from sqlalchemy import engine_from_config, pool
from alembic import context

# 导入模型
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db.base import Base
from app.db import models  # noqa

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从环境变量覆盖
db_url = os.getenv("DATABASE_URL_SYNC", "postgresql://temu:temu_dev_only@postgres:5432/temu_workflow")
config.set_main_option("sqlalchemy.url", db_url.replace("+asyncpg", ""))

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()