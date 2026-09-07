"""Temu 适配器客户端 — 主后端调用适配器微服务

W5-D2：错误分类映射 + W5-D4 异步查询支持
"""
import httpx
from typing import Any, Optional
from loguru import logger
from app.core.config import settings


class TemuAdapterClient:
    """封装所有 Temu API 调用，含超时、重试、错误分类"""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.TEMU_API_BASE
        self.timeout = httpx.Timeout(30.0, connect=5.0)

    async def publish_product(
        self,
        idempotency_key: str,
        shop_id: str,
        listing_snapshot: dict,
        simulate_error: Optional[str] = None,
    ) -> dict[str, Any]:
        """发布商品到 Temu

        Args:
            idempotency_key: 幂等键（PRD FR-083）
            shop_id: 店铺 ID
            listing_snapshot: 二审通过后的不可变快照
            simulate_error: 仅 mock 模式，用于测试错误注入

        Returns:
            {success, platform_*, error_class, error_message, is_async, ...}
        """
        payload = {
            "idempotency_key": idempotency_key,
            "shop_id": shop_id,
            "listing_snapshot": listing_snapshot,
            "candidate_title": listing_snapshot.get("title", ""),
            "candidate_price": listing_snapshot.get("attributes", {}).get("price"),
            "candidate_images": listing_snapshot.get("image_urls", []),
            "category_id": listing_snapshot.get("category_id"),
            "attributes": listing_snapshot.get("attributes", {}),
        }
        headers = {}
        if simulate_error:
            headers["X-Simulate-Error"] = simulate_error

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/products/publish",
                    json=payload, headers=headers,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            logger.warning(f"Temu adapter network error: {e}")
            return {
                "success": False,
                "error_class": "retryable",
                "error_message": f"network: {e}",
            }

        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": data.get("success", False),
                "platform_product_id": data.get("platform_product_id"),
                "platform_task_id": data.get("platform_task_id"),
                "platform_request_id": data.get("platform_request_id"),
                "platform_status": data.get("platform_status"),
                "is_async": data.get("is_async", False),
                "error_class": None,
            }

        # 错误 → 调适配器的分类端点
        try:
            error_detail = resp.json().get("detail", str(resp.status_code))
        except Exception:
            error_detail = str(resp.status_code)

        classification = await self._classify_error(resp.status_code, str(error_detail))
        return {
            "success": False,
            "error_class": classification["error_class"],
            "error_message": error_detail,
        }

    async def _classify_error(self, status_code: int, error_detail: str) -> dict:
        """调适配器的错误分类端点"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/utils/classify-error",
                    params={"status_code": status_code, "error_code": error_detail[:200]},
                )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        # 兜底映射
        if status_code == 429:
            return {"error_class": "retryable", "retry_after_sec": 60}
        if status_code in (401,):
            return {"error_class": "need_auth"}
        if status_code >= 500:
            return {"error_class": "retryable", "retry_after_sec": 30}
        return {"error_class": "fatal"}

    async def query_product(
        self,
        platform_task_id: Optional[str] = None,
        platform_product_id: Optional[str] = None,
    ) -> dict:
        """查询异步发布结果"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/products/query",
                    json={
                        "platform_task_id": platform_task_id,
                        "platform_product_id": platform_product_id,
                    },
                )
            return resp.json()
        except Exception as e:
            logger.warning(f"Temu query error: {e}")
            return {"platform_status": "unknown", "error_message": str(e)}

    async def search_categories(self, keyword: str, site: str = "us") -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/categories/search",
                    json={"keyword": keyword, "site": site},
                )
            return resp.json().get("items", [])
        except Exception:
            return []


temu_client = TemuAdapterClient()