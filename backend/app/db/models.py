"""MVP 核心数据模型 — 12 张表，覆盖 PRD §14 的核心实体

未包含的表（V1.1/V1.2 实现）：
- roles / permissions / user_roles → MVP 用最简单的 users + role 字段
- shop_credentials → 暂用 users.encrypted_credentials 字段代替
- source_products_raw → 暂不分离原始快照
- candidate_skus / listing_skus → 合并到 listing_drafts.attributes JSONB
- product_media → 合并到 candidate.image_urls + listing.image_urls JSONB
- filter_rule_versions / score_model_versions / category_dictionaries → 暂用 config 表
- publish_attempts → 合并到 publish_jobs.attempts JSONB
- platform_products → 合并到 publish_jobs.platform_* 字段
- system_configs → 暂用环境变量
- state_history / audit_logs → 合并到 events 表
"""
from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, Numeric, Boolean, DateTime, ForeignKey, Text, JSON,
    UniqueConstraint, Index, Enum as SAEnum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid
import enum

from app.db import UUID, JSONB  # 跨数据库兼容类型（PG 原生 / SQLite CHAR(36)）
from app.db.base import Base
from app.db import UUID, JSONB  # 跨数据库兼容类型


# ============ 默认值函数 ============
def _uuid():
    return uuid.uuid4()

def _now():
    return datetime.now(timezone.utc)


# ============ 枚举 ============
class BatchStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CandidateStatus(str, enum.Enum):
    IMPORTED = "imported"
    NORMALIZED = "normalized"
    FILTERED_OUT = "filtered_out"
    SCORED = "scored"
    FIRST_REVIEW = "first_review"
    CONTENT_GENERATING = "content_generating"
    EDITING = "editing"
    SECOND_REVIEW = "second_review"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHING = "publishing"
    PLATFORM_REVIEWING = "platform_reviewing"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"
    NOT_SELECTED = "not_selected"
    REJECTED_1 = "rejected_1"
    REJECTED_2 = "rejected_2"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"
    CLOSED = "closed"


class ReviewStage(str, enum.Enum):
    FIRST = "first"
    SECOND = "second"


class ReviewDecision(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    RETURN = "return"


class PublishStatus(str, enum.Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PUBLISHED = "published"
    FAILED = "failed"


# ============ 1. shops — Temu 店铺 ============
class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    site: Mapped[str] = mapped_column(String(50))  # us / uk / de ...
    merchant_type: Mapped[str] = mapped_column(String(50))  # full / half / self
    target_language: Mapped[str] = mapped_column(String(20), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    encrypted_credentials: Mapped[dict] = mapped_column(JSONB, default=dict)  # {access_token, app_key, ...}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ============ 2. data_sources — 候选来源 ============
class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(50))  # csv / xlsx / internal_api / third_party
    owner: Mapped[str] = mapped_column(String(100))  # 责任人
    authorization_note: Mapped[str | None] = mapped_column(Text)
    config_ref: Mapped[dict | None] = mapped_column(JSONB)  # {file_path, api_url, api_key, ...}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ============ 3. users — 用户 + 角色（简化版）============
class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(50))  # admin / operator / editor / reviewer / publisher / readonly
    shop_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("shops.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ============ 4. selection_batches — 每日批次 ============
class SelectionBatch(Base):
    __tablename__ = "selection_batches"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    shop_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("shops.id"))
    business_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    batch_type: Mapped[str] = mapped_column(String(20), default="daily")
    target_count: Mapped[int] = mapped_column(Integer, default=20)
    status: Mapped[BatchStatus] = mapped_column(SAEnum(BatchStatus), default=BatchStatus.RUNNING)
    statistics: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 统计字段：imported / deduped / filtered / scored / recommended / first_approved / second_approved / published / failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # PRD §14.1 关键唯一约束
        UniqueConstraint("shop_id", "business_date", "batch_type", name="uq_batch_per_day"),
        Index("ix_batches_shop_date", "shop_id", "business_date"),
    )


# ============ 5. candidate_products — 候选商品（标准化后）============
class CandidateProduct(Base):
    __tablename__ = "candidate_products"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("selection_batches.id"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("data_sources.id"))
    source_product_id: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(Text)

    # 标准化字段
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(200))
    price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    weight_g: Mapped[int | None] = mapped_column(Integer)
    dimensions: Mapped[dict | None] = mapped_column(JSONB)  # {l, w, h}
    image_urls: Mapped[list] = mapped_column(JSONB, default=list)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    supplier_sku: Mapped[str | None] = mapped_column(String(200))

    # 去重
    dedupe_key: Mapped[str] = mapped_column(String(500))

    # 状态机
    status: Mapped[CandidateStatus] = mapped_column(SAEnum(CandidateStatus), default=CandidateStatus.IMPORTED)

    # 评分（冗余便于查询）
    total_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))

    # 乐观锁（W2-D4）
    version: Mapped[int] = mapped_column(Integer, default=1)

    # 权限/权利
    rights_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    rights_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_candidate_batch", "batch_id"),
        Index("ix_candidate_status", "status"),
        Index("ix_candidate_score", "total_score"),
        UniqueConstraint("batch_id", "dedupe_key", name="uq_candidate_dedupe"),
    )


# ============ 6. filter_results — 规则命中结果 ============
class FilterResult(Base):
    __tablename__ = "filter_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("candidate_products.id"))
    rule_code: Mapped[str] = mapped_column(String(100))  # e.g. BANNED_KEYWORD
    rule_version: Mapped[str] = mapped_column(String(50))
    rule_type: Mapped[str] = mapped_column(String(20))  # hard / soft
    action: Mapped[str] = mapped_column(String(20))  # filter_out / flag / score_deduct
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ============ 7. product_scores — 评分结果（多维度）============
class ProductScore(Base):
    __tablename__ = "product_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("candidate_products.id"), unique=True)
    model_version: Mapped[str] = mapped_column(String(50))
    dimension_scores: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {heat: 0-100, competition: 0-100, profit: 0-100, trend: 0-100, ratings: 0-100, risk: 0-100}
    total_score: Mapped[float] = mapped_column(Numeric(5, 2))
    confidence: Mapped[float] = mapped_column(Numeric(3, 2))
    reason: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[list] = mapped_column(JSONB, default=list)
    data_gaps: Mapped[list] = mapped_column(JSONB, default=list)
    # 规则评分时无 token；LLM 评分时有
    llm_prompt_version: Mapped[str | None] = mapped_column(String(50))
    llm_tokens_in: Mapped[int | None] = mapped_column(Integer)
    llm_tokens_out: Mapped[int | None] = mapped_column(Integer)
    llm_cost_cny: Mapped[float | None] = mapped_column(Numeric(8, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ============ 8. listing_drafts — 上品草稿（资料生成）============
class ListingDraft(Base):
    __tablename__ = "listing_drafts"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("candidate_products.id"))
    shop_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("shops.id"))

    # 上品字段（目标语言）
    title: Mapped[str | None] = mapped_column(String(500))
    bullet_points: Mapped[list] = mapped_column(JSONB, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[str | None] = mapped_column(String(200))  # Temu 类目
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)  # SKU/规格/价格/重量等
    image_urls: Mapped[list] = mapped_column(JSONB, default=list)

    status: Mapped[CandidateStatus] = mapped_column(SAEnum(CandidateStatus), default=CandidateStatus.EDITING)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)

    # 发布快照（二审通过后冻结）
    publish_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    snapshot_version: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_listing_candidate", "candidate_id"),
        Index("ix_listing_status", "status"),
    )


# ============ 8b. listing_versions — 资料快照（每次编辑/AI生成）============
class ListingVersion(Base):
    """listing 资料的版本快照（W4-D2）

    每次 AI 生成 / 人工编辑 → 创建快照（含原因）
    二审通过后的快照会被冻结 → publish_snapshot 引用
    """
    __tablename__ = "listing_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("listing_drafts.id"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)  # 完整 listing 字段
    change_reason: Mapped[str] = mapped_column(String(200))  # ai_generated / human_edit / rollback
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("users.id"))
    created_by_name: Mapped[str | None] = mapped_column(String(100))  # 冗余便于查询
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)  # 二审后冻结
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("listing_id", "version", name="uq_listing_version"),
        Index("ix_listing_version_listing", "listing_id"),
    )


# ============ 9. review_tasks — 审核任务 ============
class ReviewTask(Base):
    __tablename__ = "review_tasks"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("candidate_products.id"))
    listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("listing_drafts.id"))
    stage: Mapped[ReviewStage] = mapped_column(SAEnum(ReviewStage))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / approved / rejected / returned
    decision_reason: Mapped[str | None] = mapped_column(String(200))
    decision_comment: Mapped[str | None] = mapped_column(Text)
    snapshot_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ============ 10. publish_jobs — 发布任务（含幂等）============
class PublishJob(Base):
    __tablename__ = "publish_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=_uuid)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("listing_drafts.id"))
    shop_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("shops.id"))
    snapshot_version: Mapped[int] = mapped_column(Integer)

    # 幂等键：每店铺+每发布意图唯一（PRD §11 / FR-083）
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)

    status: Mapped[PublishStatus] = mapped_column(SAEnum(PublishStatus), default=PublishStatus.PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_class: Mapped[str | None] = mapped_column(String(50))  # retryable / fatal / need_auth

    # 平台返回
    platform_product_id: Mapped[str | None] = mapped_column(String(200))
    platform_task_id: Mapped[str | None] = mapped_column(String(200))
    platform_request_id: Mapped[str | None] = mapped_column(String(200))
    platform_status: Mapped[str | None] = mapped_column(String(50))
    attempts: Mapped[list] = mapped_column(JSONB, default=list)  # 每次请求的脱敏摘要

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_publish_idempotency"),
        Index("ix_publish_status", "status"),
        Index("ix_publish_shop_listing", "shop_id", "listing_id"),
    )


# ============ 11. events — 状态机 + 审计日志（合并）============
class Event(Base):
    """统一事件流：状态流转 + 审核决策 + 配置变更"""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(50))  # batch / candidate / listing / job
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID)
    event_type: Mapped[str] = mapped_column(String(100))  # state_change / review_decision / publish_attempt ...
    from_status: Mapped[str | None] = mapped_column(String(50))
    to_status: Mapped[str | None] = mapped_column(String(50))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("users.id"))
    actor_name: Mapped[str | None] = mapped_column(String(100))  # 冗余
    reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(100))  # 链路追踪
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_event_entity", "entity_type", "entity_id"),
        Index("ix_event_created", "created_at"),
        Index("ix_event_trace", "trace_id"),
    )


# ============ 12. rule_versions — 规则/模型/字典版本（合并）============
class ConfigVersion(Base):
    """存规则版本、评分模型版本、类目字典版本 — 用 type 字段区分"""
    __tablename__ = "config_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_type: Mapped[str] = mapped_column(String(50))  # filter_rule / score_model / category_dict
    version: Mapped[str] = mapped_column(String(50))
    definition: Mapped[dict] = mapped_column(JSONB)  # 规则集合 / 模型权重 / 字典
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("config_type", "version", name="uq_config_version"),
    )


# ============ V2.0 — 13. sales_records — 销量反馈 ============
class SalesRecord(Base):
    """V2.0 销量反馈记录（PRD §19 V2.0 业务闭环）

    数据来源：Temu 订单 API（T+1 拉取）或客户回传 CSV
    """
    __tablename__ = "sales_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("listing_drafts.id"), index=True)
    platform_product_id: Mapped[str | None] = mapped_column(String(200), index=True)
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD (Beijing)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    refund_count: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float | None] = mapped_column(Numeric(3, 2))
    category_rank: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default="temu_api")  # temu_api / csv
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("listing_id", "date", "source", name="uq_sales_per_day_per_source"),
        Index("ix_sales_date", "date"),
    )


# ============ V2.0 — 14. model_drift — 评分模型偏差 ============
class ModelDrift(Base):
    """V2.0 评分模型偏差报告（PRD §19）

    每周跑一次校准：拿 30 天 realized sales vs 当时的 predicted_score，
    算 calibration_error + 每维 bias + 推荐权重调整。

    关键约束（PRD §6.5）：status 默认 generated，人工审核后才可 applied/ignored。
    apply 端点只创建 ConfigVersion 草稿，不自动激活。
    """
    __tablename__ = "model_drift"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version: Mapped[str] = mapped_column(String(50))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    window_start: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    window_end: Mapped[str] = mapped_column(String(10))
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    predicted_score_avg: Mapped[float | None] = mapped_column(Numeric(5, 2))
    realized_score_avg: Mapped[float | None] = mapped_column(Numeric(5, 2))
    calibration_error: Mapped[float | None] = mapped_column(Numeric(5, 2))  # realized - predicted
    dimension_errors_json: Mapped[dict] = mapped_column(JSONB, default=dict)  # {dim: bias}
    recommended_weight_adjustments_json: Mapped[dict] = mapped_column(JSONB, default=dict)  # {dim: new_weight}
    status: Mapped[str] = mapped_column(String(20), default="generated")  # generated / applied / ignored
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("users.id"), nullable=True)
    applied_config_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("config_versions.id"), nullable=True)

    __table_args__ = (
        Index("ix_drift_evaluated", "evaluated_at"),
        Index("ix_drift_status", "status"),
    )