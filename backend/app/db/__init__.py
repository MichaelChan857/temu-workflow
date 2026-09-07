from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, Numeric, Boolean, DateTime, ForeignKey, Text, JSON,
    UniqueConstraint, Index, Enum as SAEnum, TypeDecorator, CHAR
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB
import uuid
import enum

from app.db.base import Base


def _uuid():
    return uuid.uuid4()

def _now():
    return datetime.now(timezone.utc)


# ============ 跨数据库兼容类型 ============
class GUID(TypeDecorator):
    """跨数据库 UUID（SQLite 用 CHAR(36)，PostgreSQL 用原生 UUID）"""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class JSONType(TypeDecorator):
    """跨数据库 JSON"""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_JSONB)
        return dialect.type_descriptor(JSON)


# 别名
UUID = GUID
JSONB = JSONType