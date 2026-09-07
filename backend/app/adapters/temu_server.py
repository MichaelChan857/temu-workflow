"""Temu Partner Platform 适配器（独立微服务）

PRD §16 / FR-080~089：封装 Temu 官方开放 API
- mock 模式：开发/测试用，预置数据
- sandbox 模式：联调 Temu 沙箱环境（需凭据）
- live 模式：生产真实 API

启动：uvicorn app.adapters.temu_server:app --host 0.0.0.0 --port 8001 --reload
"""
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Literal, Optional
import os
import time
import uuid
import json
import hashlib
import hmac
import logging
import asyncio
import random
from datetime import datetime, timezone
from enum import Enum

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("temu-adapter")

app = FastAPI(title="Temu Adapter", version="0.2.0")


# ============ 运行模式 ============
class RunMode(str, Enum):
    MOCK = "mock"          # 内部数据，零网络
    SANDBOX = "sandbox"    # Temu 沙箱（待申请）
    LIVE = "live"          # Temu 生产


USE_MOCK = os.getenv("TEMU_USE_MOCK", "true").lower() == "true"
RUN_MODE = RunMode.MOCK if USE_MOCK else RunMode(os.getenv("TEMU_RUN_MODE", "sandbox"))

APP_KEY = os.getenv("TEMU_APP_KEY", "mock_app_key")
APP_SECRET = os.getenv("TEMU_APP_SECRET", "mock_app_secret")
ACCESS_TOKEN = os.getenv("TEMU_ACCESS_TOKEN", "mock_access_token")

PARTNER_BASE_MOCK = "http://localhost:8001"
PARTNER_BASE_SANDBOX = os.getenv("TEMU_SANDBOX_BASE", "https://open-sandbox.temu.com/api")
PARTNER_BASE_LIVE = os.getenv("TEMU_LIVE_BASE", "https://open.temu.com/api")

PARTNER_BASE = {
    RunMode.MOCK: PARTNER_BASE_MOCK,
    RunMode.SANDBOX: PARTNER_BASE_SANDBOX,
    RunMode.LIVE: PARTNER_BASE_LIVE,
}[RUN_MODE]

log.info(f"Temu Adapter running in mode: {RUN_MODE.value}")


# ============ Schemas ============
class PublishRequest(BaseModel):
    idempotency_key: str
    shop_id: str
    listing_snapshot: dict = Field(..., description="二审通过后的不可变快照")
    candidate_title: str
    candidate_price: Optional[float] = None
    candidate_images: list[str] = []
    category_id: Optional[str] = None
    attributes: dict = {}
    sku_list: list[dict] = []  # [{sku_id, price, quantity, image_url}]


class PublishResponse(BaseModel):
    success: bool
    platform_product_id: Optional[str] = None
    platform_task_id: Optional[str] = None
    platform_request_id: Optional[str] = None
    platform_status: str  # submitted / published / review_failed / platform_error
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    is_async: bool = False


class QueryRequest(BaseModel):
    platform_task_id: Optional[str] = None
    platform_product_id: Optional[str] = None


class QueryResponse(BaseModel):
    platform_status: str
    platform_product_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class CategoryQueryRequest(BaseModel):
    keyword: str
    site: str = "us"


class CategoryItem(BaseModel):
    category_id: str
    name: str
    score: float = 0.0


class CategoryQueryResponse(BaseModel):
    items: list[CategoryItem]


class ErrorClassifyResponse(BaseModel):
    """W5-D2：错误分类（4 类）"""
    error_class: Literal["retryable", "fatal", "need_auth", "need_fix"]
    retry_after_sec: Optional[int] = None
    description: str


# ============ Temu 签名（PRD §16 FR-080~089）============
# V2.0 — 多算法支持：v1 / v2 / v3 三种签名算法可切换
# 默认 v2（与官方文档通用模式一致），可通过 env `TEMU_SIGN_ALGO` 切换
# 真实算法在联调 Temu Partner Platform 时确认
SIGN_ALGO = os.getenv("TEMU_SIGN_ALGO", "v2").lower()  # v1 | v2 | v3


def sign_request_v1(method: str, path: str, body: dict, timestamp_ms: int, nonce: str) -> str:
    """V1 签名：METHOD\nPATH\nTIMESTAMP\nNONCE\nAPP_SECRET(纯拼接)

    V1 是 Temu 早期合作伙伴的简单算法，仅在文档明确指定 v1 时使用。
    """
    canonical = f"{method.upper()}{path}{timestamp_ms}{nonce}{APP_SECRET}"
    return hashlib.md5(canonical.encode()).hexdigest()


def sign_request_v2(method: str, path: str, body: dict, timestamp_ms: int, nonce: str) -> str:
    """V2 签名：HMAC-SHA256(METHOD\\nPATH\\nTS\\nNONCE\\nSHA256(BODY), APP_SECRET)

    通用签名模式，与大部分开放平台兼容。
    """
    body_hash = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    canonical = f"{method.upper()}\n{path}\n{timestamp_ms}\n{nonce}\n{body_hash}"
    sig = hmac.new(APP_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return sig


def sign_request_v3(method: str, path: str, body: dict, timestamp_ms: int, nonce: str) -> str:
    """V3 签名：HMAC-SHA256(METHOD + PATH + TS + NONCE + BODY_SORTED_JSON, APP_SECRET)

    V3 把整个 body JSON(非 hash)参与签名，更严格防篡改。某些开放平台用此模式。
    """
    body_str = json.dumps(body, sort_keys=True, separators=(",", ":"))
    canonical = f"{method.upper()}{path}{timestamp_ms}{nonce}{body_str}"
    sig = hmac.new(APP_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return sig


_SIGNERS = {
    "v1": sign_request_v1,
    "v2": sign_request_v2,
    "v3": sign_request_v3,
}


def sign_request(method: str, path: str, body: dict, timestamp_ms: int, nonce: str) -> str:
    """按 TEMU_SIGN_ALGO env 选择签名算法

    真实生产环境联调时:
      1. 抓 Temu Partner Platform 文档
      2. 如 v2 不匹配，env 改 TEMU_SIGN_ALGO=v1 或 v3
      3. 再次联调
    """
    signer = _SIGNERS.get(SIGN_ALGO)
    if signer is None:
        raise ValueError(
            f"unknown TEMU_SIGN_ALGO={SIGN_ALGO!r}, valid: {list(_SIGNERS.keys())}"
        )
    sig = signer(method, path, body, timestamp_ms, nonce)
    log.debug(f"sign_request algo={SIGN_ALGO} sig={sig[:16]}...")
    return sig


def auto_detect_algo(method: str, path: str, body: dict) -> str | None:
    """联调时自动探测:逐个算法重试直到 200 OK

    用法:
      from app.adapters.temu_server import auto_detect_algo
      algo = await auto_detect_algo("POST", "/v1/products/publish", payload)
      if algo: os.environ["TEMU_SIGN_ALGO"] = algo
    """
    # 此函数仅占位 — 真实实现见 sandbox 联调脚本 scripts/test_temu_signature.py
    # 见 docs/STAGE_D_CHECKLIST.md §D.4 验证签名算法
    raise NotImplementedError(
        "auto_detect_algo 需在 sandbox 联调时实现。参考 scripts/test_temu_signature.py"
    )


def build_headers(method: str, path: str, body: dict) -> dict:
    """构造带签名的请求头"""
    ts = int(time.time() * 1000)
    nonce = uuid.uuid4().hex
    sig = sign_request(method, path, body, ts, nonce)
    return {
        "Content-Type": "application/json; charset=utf-8",
        "X-App-Key": APP_KEY,
        "X-Access-Token": ACCESS_TOKEN,
        "X-Timestamp": str(ts),
        "X-Nonce": nonce,
        "X-Signature": sig,
        "X-Idempotency-Key": body.get("idempotency_key", ""),
    }


# ============ Mock 数据 ============
MOCK_PRODUCTS: dict[str, dict] = {}
MOCK_FAILURE_MODES = {
    "rate_limit": (429, "rate_limit_exceeded"),
    "auth_expired": (401, "token_expired"),
    "server_error": (500, "internal_server_error"),
    "validation": (400, "missing_required_field:sku_quantity"),
    "permission": (403, "permission_denied"),
    "platform_review_failed": (200, "platform_review_failed"),
}

MOCK_CATEGORIES = {
    "pet": [
        {"category_id": "PET-001", "name": "宠物用品 > 宠物玩具", "score": 92.0},
        {"category_id": "PET-002", "name": "宠物用品 > 宠物食具", "score": 78.0},
    ],
    "kitchen": [
        {"category_id": "KIT-001", "name": "厨房用品 > 餐具", "score": 88.0},
        {"category_id": "KIT-002", "name": "厨房用品 > 烘焙工具", "score": 75.0},
    ],
    "phone": [
        {"category_id": "PHN-001", "name": "手机配件 > 手机壳", "score": 95.0},
        {"category_id": "PHN-002", "name": "手机配件 > 充电器", "score": 70.0},
    ],
}


# ============ 健康检查 ============
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": RUN_MODE.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "partner_base": PARTNER_BASE,
    }


# ============ 发布商品 ============
@app.post("/v1/products/publish", response_model=PublishResponse)
async def publish_product(
    req: PublishRequest,
    x_simulate_error: Optional[str] = Header(None, alias="X-Simulate-Error"),
):
    """发布商品到 Temu

    错误注入：测试时通过 X-Simulate-Error 头模拟不同错误
      - rate_limit | auth_expired | server_error | validation | permission
    """
    log.info(f"publish: idem={req.idempotency_key} mode={RUN_MODE.value} simulate={x_simulate_error}")

    # === Mock 模式（含错误注入）===
    if RUN_MODE == RunMode.MOCK:
        if x_simulate_error and x_simulate_error in MOCK_FAILURE_MODES:
            status, code = MOCK_FAILURE_MODES[x_simulate_error]
            raise HTTPException(status_code=status, detail=code)

        # 已存在（幂等复用）
        if req.idempotency_key in MOCK_PRODUCTS:
            data = MOCK_PRODUCTS[req.idempotency_key]
            return PublishResponse(
                success=True,
                platform_product_id=data["platform_product_id"],
                platform_task_id=data["platform_task_id"],
                platform_request_id=data["platform_request_id"],
                platform_status=data["platform_status"],
                is_async=False,
            )

        # 新商品：模拟"异步受理"（W5-D4 场景）
        task_id = f"TT-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        product_id = f"TP-{uuid.uuid4().hex[:10]}"
        MOCK_PRODUCTS[req.idempotency_key] = {
            "platform_product_id": product_id,
            "platform_task_id": task_id,
            "platform_request_id": f"TR-{uuid.uuid4().hex[:12]}",
            "platform_status": "submitted",  # 异步初始状态
        }
        return PublishResponse(
            success=True,
            platform_product_id=None,  # 异步模式下尚无
            platform_task_id=task_id,
            platform_request_id=MOCK_PRODUCTS[req.idempotency_key]["platform_request_id"],
            platform_status="submitted",
            is_async=True,
        )

    # === Sandbox / Live 模式（W5-D1 待联调）===
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        path = "/v1/products/publish"
        headers = build_headers("POST", path, req.model_dump())
        try:
            resp = await client.post(
                f"{PARTNER_BASE}{path}",
                headers=headers,
                json=req.model_dump(),
            )
        except httpx.HTTPError as e:
            raise HTTPException(503, f"network error: {e}")

    if resp.status_code == 200:
        data = resp.json()
        # 三态分发（PRD FR-085）
        return PublishResponse(
            success=data.get("success", False),
            platform_product_id=data.get("platform_product_id"),
            platform_task_id=data.get("platform_task_id"),
            platform_request_id=data.get("platform_request_id"),
            platform_status=data.get("platform_status"),
            is_async=data.get("is_async", False),
        )
    elif resp.status_code == 429:
        raise HTTPException(429, "rate_limited")
    elif resp.status_code == 401:
        raise HTTPException(401, "token_expired")
    else:
        raise HTTPException(resp.status_code, resp.text[:500])


# ========== 查询发布结果 ==========
@app.post("/v1/products/query", response_model=QueryResponse)
async def query_product(req: QueryRequest):
    """查询异步发布结果"""
    log.info(f"query: task={req.platform_task_id} product={req.platform_product_id}")

    if RUN_MODE == RunMode.MOCK:
        # Mock：根据 task_id 查找
        for idem, data in MOCK_PRODUCTS.items():
            if data["platform_task_id"] == req.platform_task_id or data["platform_product_id"] == req.platform_product_id:
                return QueryResponse(
                    platform_status=data["platform_status"],
                    platform_product_id=data["platform_product_id"],
                )
        # 默认：模拟异步任务最终成功
        return QueryResponse(
            platform_status="published",
            platform_product_id=req.platform_product_id or f"TP-{uuid.uuid4().hex[:10]}",
        )

    # TODO: Sandbox/Live 实现
    raise HTTPException(501, "live mode not implemented yet")


# ========== 类目查询 ==========
@app.post("/v1/categories/search", response_model=CategoryQueryResponse)
async def search_categories(req: CategoryQueryRequest):
    if RUN_MODE == RunMode.MOCK:
        items = MOCK_CATEGORIES.get(req.keyword.lower(), [])
        return CategoryQueryResponse(items=[CategoryItem(**i) for i in items])
    raise HTTPException(501, "live mode not implemented yet")


# ========== 媒体上传 ==========
class MediaUploadRequest(BaseModel):
    image_url: str


class MediaUploadResponse(BaseModel):
    media_id: str
    url: str


@app.post("/v1/media/upload", response_model=MediaUploadResponse)
async def upload_media(req: MediaUploadRequest):
    if RUN_MODE == RunMode.MOCK:
        media_id = f"M-{hashlib.md5(req.image_url.encode()).hexdigest()[:16]}"
        return MediaUploadResponse(media_id=media_id, url=req.image_url)
    raise HTTPException(501, "live mode not implemented yet")


# ========== W5-D2：错误分类（独立端点）=========
@app.post("/v1/utils/classify-error")
async def classify_error(
    status_code: int,
    error_code: Optional[str] = None,
) -> ErrorClassifyResponse:
    """根据 HTTP 状态码 + 业务错误码返回错误分类

    4 类：
    - retryable: 网络/超时/限流/5xx → 自动重试
    - fatal: 参数错误/权限/禁限售 → 不可重试
    - need_auth: token 过期 → 需重新授权
    - need_fix: 业务字段错误 → 退回编辑
    """
    if status_code == 429 or (error_code and "rate_limit" in error_code):
        return ErrorClassifyResponse(
            error_class="retryable",
            retry_after_sec=60,
            description="rate_limited — 等待退避后重试",
        )
    if status_code in (401, 403) and error_code and "token" in error_code.lower():
        return ErrorClassifyResponse(
            error_class="need_auth",
            retry_after_sec=None,
            description="token 过期 — 停止发布，等待重新授权",
        )
    if status_code == 403:
        return ErrorClassifyResponse(
            error_class="fatal",
            retry_after_sec=None,
            description="permission_denied — 无权限",
        )
    if status_code >= 500:
        return ErrorClassifyResponse(
            error_class="retryable",
            retry_after_sec=30,
            description="server_error — 平台临时错误",
        )
    if status_code == 400:
        return ErrorClassifyResponse(
            error_class="need_fix",
            retry_after_sec=None,
            description="validation_error — 业务字段错误，需退回编辑",
        )
    return ErrorClassifyResponse(
        error_class="fatal",
        retry_after_sec=None,
        description=f"unknown status={status_code}",
    )


# ========== W5-D5：模拟 worker（mock 异步任务推进）=========
@app.post("/v1/admin/advance-async")
async def advance_async(idempotency_key: str, to_status: str = "published"):
    """仅 mock 模式：把某个异步任务推进到指定状态（用于模拟异步轮询）"""
    if RUN_MODE != RunMode.MOCK:
        raise HTTPException(400, "only in mock mode")
    if idempotency_key in MOCK_PRODUCTS:
        MOCK_PRODUCTS[idempotency_key]["platform_status"] = to_status
        return {"ok": True, "status": to_status}
    raise HTTPException(404, "idempotency_key not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)