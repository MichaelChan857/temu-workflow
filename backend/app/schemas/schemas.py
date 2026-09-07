"""Pydantic schemas — API 入参出参"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID


# ============ 一审相关 ============
class CandidateSummary(BaseModel):
    id: UUID
    title: str
    category: Optional[str]
    price: Optional[float]
    total_score: Optional[float]
    confidence: Optional[float]
    status: str
    image_urls: list[str] = []
    created_at: datetime

    class Config:
        from_attributes = True


class CandidateDetail(CandidateSummary):
    description: Optional[str]
    brand: Optional[str]
    cost: Optional[float]
    currency: str
    weight_g: Optional[int]
    dimensions: Optional[dict]
    supplier_sku: Optional[str]
    rights_confirmed: bool
    dimension_scores: Optional[dict] = None
    reason: Optional[str] = None
    risks: list = []
    data_gaps: list = []
    filter_hits: list = []


class ReviewDecision(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject|return)$")
    reason_code: Optional[str] = None
    comment: Optional[str] = None


class BatchListItem(BaseModel):
    id: UUID
    business_date: str
    status: str
    target_count: int
    statistics: dict = {}
    started_at: datetime

    class Config:
        from_attributes = True


# ============ 发布相关 ============
class PublishRequest(BaseModel):
    listing_id: UUID
    shop_id: UUID


class PublishResponse(BaseModel):
    job_id: UUID
    status: str
    platform_status: Optional[str] = None
    platform_product_id: Optional[str] = None
    error_message: Optional[str] = None


# ============ 通用 ============
class HealthResponse(BaseModel):
    status: str
    services: dict