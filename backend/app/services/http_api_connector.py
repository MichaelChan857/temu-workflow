"""通用 HTTP API 连接器 — V1.1-A1

支持任意 REST API 作为候选来源：
  - 内部商品库
  - 供应商 API（1688 / 义乌购 / 阿里云市场 等）
  - 第三方数据（Sorftime / Jungle Scout / Bright Data 等）

配置项：
  - url: 列表端点 URL
  - method: GET / POST
  - auth: {type: none|basic|bearer|apikey, ...}
  - pagination: {type: page|offset|cursor, ...}
  - mapping: 字段映射 {api_field → internal_field}
  - items_path: 响应中 items 的 JSON 路径（如 'data.items'）
"""
import httpx
import asyncio
import json
from typing import Iterator, Optional
from dataclasses import dataclass, field
from app.services.connectors import BaseConnector, ConnectorMetadata
import logging

log = logging.getLogger(__name__)


@dataclass
class HttpApiConfig:
    url: str
    method: str = "GET"           # GET / POST
    auth_type: str = "none"        # none / basic / bearer / apikey
    auth_token: str = ""
    auth_username: str = ""
    auth_password: str = ""
    auth_apikey_header: str = "X-Api-Key"
    headers: dict = field(default_factory=dict)
    pagination_type: str = "none"  # none / page / offset / cursor / link
    page_size: int = 100
    page_param: str = "page"
    offset_param: str = "offset"
    cursor_param: str = "cursor"
    cursor_response_field: str = "next_cursor"
    max_pages: int = 50
    items_path: str = "items"       # JSON path to items array
    mapping: dict = field(default_factory=dict)  # api_field → internal_field


class HttpApiConnector(BaseConnector):
    """通用 HTTP API 连接器 — 支持 4 类分页 + 4 类认证"""

    def __init__(self, metadata: ConnectorMetadata, config: HttpApiConfig):
        super().__init__(metadata)
        self.config = config

    def fetch(self, **kwargs) -> Iterator[dict]:
        """拉取所有候选商品"""
        if self.config.pagination_type == "none":
            for item in self._fetch_page():
                yield self._map_item(item)
        elif self.config.pagination_type == "page":
            for page in range(1, self.config.max_pages + 1):
                items = list(self._fetch_page(page=page))
                if not items:
                    break
                for item in items:
                    yield self._map_item(item)
                if len(items) < self.config.page_size:
                    break
        elif self.config.pagination_type == "offset":
            offset = 0
            for _ in range(self.config.max_pages):
                items = list(self._fetch_page(offset=offset))
                if not items:
                    break
                for item in items:
                    yield self._map_item(item)
                if len(items) < self.config.page_size:
                    break
                offset += self.config.page_size
        elif self.config.pagination_type == "cursor":
            cursor: Optional[str] = None
            for _ in range(self.config.max_pages):
                items = list(self._fetch_page(cursor=cursor))
                if not items:
                    break
                for item in items:
                    yield self._map_item(item)
                # 提取下一个 cursor
                # 注：真实实现需要响应访问
                break  # MVP 简化

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = self._request(client)
                return resp.status_code < 500
        except Exception as e:
            log.warning(f"HttpApiConnector health check failed: {e}")
            return False

    # ============ 内部 ============
    def _build_headers(self) -> dict:
        headers = dict(self.config.headers)
        if self.config.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {self.config.auth_token}"
        elif self.config.auth_type == "basic":
            import base64
            cred = base64.b64encode(
                f"{self.config.auth_username}:{self.config.auth_password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {cred}"
        elif self.config.auth_type == "apikey":
            headers[self.config.auth_apikey_header] = self.config.auth_token
        return headers

    def _request(self, client: httpx.Client) -> httpx.Response:
        params = {}
        return client.request(
            method=self.config.method,
            url=self.config.url,
            headers=self._build_headers(),
            params=params or None,
            timeout=30.0,
        )

    def _fetch_page(self, page: int = 1, offset: int = 0, cursor: Optional[str] = None) -> list[dict]:
        with httpx.Client(timeout=30.0) as client:
            params = {}
            if self.config.pagination_type == "page":
                params[self.config.page_param] = page
                params["page_size"] = self.config.page_size
            elif self.config.pagination_type == "offset":
                params[self.config.offset_param] = offset
                params["limit"] = self.config.page_size
            elif self.config.pagination_type == "cursor" and cursor:
                params[self.config.cursor_param] = cursor

            resp = client.request(
                method=self.config.method,
                url=self.config.url,
                headers=self._build_headers(),
                params=params,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        # 提取 items（按 JSON path）
        return self._extract_items(data)

    def _extract_items(self, data: dict | list) -> list[dict]:
        if isinstance(data, list):
            return data
        parts = self.config.items_path.split(".")
        cur = data
        for p in parts:
            if isinstance(cur, dict):
                cur = cur.get(p, [])
            else:
                return []
        if isinstance(cur, list):
            return cur
        return []

    def _map_item(self, raw: dict) -> dict:
        """将 API 字段映射到内部标准字段"""
        if not self.config.mapping:
            return raw

        result = {}
        for internal_field, api_field in self.config.mapping.items():
            v = raw.get(api_field)
            if v is not None:
                result[internal_field] = v
        return result


# ============ 预设：内部商品库 ============
class InternalProductLibrary(HttpApiConnector):
    """内部商品库预设 — 假设接口约定

    GET /api/v1/products?page=1&page_size=100
    Response: { "items": [{"product_id": "...", "title": "...", ...}] }
    """
    def __init__(self, metadata: ConnectorMetadata, base_url: str, api_key: str = ""):
        config = HttpApiConfig(
            url=f"{base_url.rstrip('/')}/api/v1/products",
            method="GET",
            auth_type="bearer" if api_key else "none",
            auth_token=api_key,
            pagination_type="page",
            page_size=100,
            items_path="items",
            mapping={
                "source_product_id": "product_id",
                "title": "title",
                "description": "description",
                "brand": "brand",
                "category": "category",
                "price": "price",
                "cost": "cost",
                "currency": "currency",
                "weight_g": "weight_g",
                "image_url_1": "main_image",
                "supplier_sku": "sku",
                "source_url": "url",
            },
        )
        super().__init__(metadata, config)


# ============ 预设：1688 ============
class Alibaba1688Connector(HttpApiConnector):
    """1688 开放平台预设 — 国内主流批发源

    GET https://gw.open.1688.com/openapi/param2/1/com.alibaba.product/alibaba.product.search
    """
    def __init__(self, metadata: ConnectorMetadata, app_key: str, app_secret: str):
        config = HttpApiConfig(
            url="https://gw.open.1688.com/openapi/param2/1/com.alibaba.product/alibaba.product.search",
            method="GET",
            auth_type="none",  # 1688 用 URL 签名认证（非 Authorization header）
            pagination_type="page",
            page_size=40,
            items_path="result.products",
            mapping={
                "source_product_id": "productId",
                "title": "subject",
                "description": "description",
                "category": "categoryName",
                "price": "price",
                "cost": "price",  # 1688 同一字段
                "currency": "currency",
                "image_url_1": "imageUrl",
                "supplier_sku": "productId",
                "source_url": "detailUrl",
            },
        )
        super().__init__(metadata, config)