"""数据源连接器抽象 — 统一不同来源

W3-D2: 抽象三类来源：
  - CSV/XLSX 文件（已实现）
  - 内部商品库 API（占位）
  - 合规第三方数据源（占位）

后续扩展：新增类型只需继承 BaseConnector 并注册
"""
from abc import ABC, abstractmethod
from typing import Iterator, Optional
from dataclasses import dataclass
import httpx


@dataclass
class ConnectorMetadata:
    source_id: str
    source_name: str
    source_type: str  # csv / xlsx / api / scraper
    authorization_note: Optional[str] = None


class BaseConnector(ABC):
    """所有数据源连接器的基类"""

    def __init__(self, metadata: ConnectorMetadata, config: dict = None):
        self.metadata = metadata
        self.config = config or {}

    @abstractmethod
    def fetch(self, **kwargs) -> Iterator[dict]:
        """拉取候选商品，返回标准化 dict 迭代器

        每个 dict 必须包含字段（与 FILE_COLUMNS 对齐）：
          source_product_id, title, description, brand, category,
          price, cost, currency, weight_g, length_cm, width_cm, height_cm,
          image_url_1, image_url_2, image_url_3, supplier_sku, source_url
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """检查连接器是否可用"""
        pass


class CSVConnector(BaseConnector):
    """CSV 文件连接器（复用文件解析器）"""
    source_type = "csv"

    def __init__(self, metadata: ConnectorMetadata, file_path: str):
        super().__init__(metadata)
        self.file_path = file_path

    def fetch(self, **kwargs) -> Iterator[dict]:
        from pathlib import Path
        from app.services.file_parser import parse_file
        content = Path(self.file_path).read_bytes()
        return parse_file(self.file_path, content)

    def health_check(self) -> bool:
        from pathlib import Path
        return Path(self.file_path).exists()


class XLSXConnector(CSVConnector):
    source_type = "xlsx"


class InternalAPIConnector(BaseConnector):
    """内部商品库 API（W3 占位，真实接入 W4）"""
    source_type = "internal_api"

    def __init__(self, metadata: ConnectorMetadata, api_url: str, api_key: str = ""):
        super().__init__(metadata)
        self.api_url = api_url
        self.api_key = api_key

    def fetch(self, **kwargs) -> Iterator[dict]:
        # TODO W4: 接入内部商品库
        # 占位实现：返回空迭代器
        return iter([])

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(self.api_url, headers={"Authorization": f"Bearer {self.api_key}"})
                return resp.status_code == 200
        except Exception:
            return False


class ThirdPartyConnector(BaseConnector):
    """合规第三方数据源（W3 占位，真实接入 V1.1）"""
    source_type = "third_party"

    def __init__(self, metadata: ConnectorMetadata, api_url: str, vendor: str = "unknown"):
        super().__init__(metadata)
        self.api_url = api_url
        self.vendor = vendor

    def fetch(self, **kwargs) -> Iterator[dict]:
        # V1.1 实现：Bright Data / Sorftime / Jungle Scout 等
        return iter([])

    def health_check(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(self.api_url)
                return resp.status_code == 200
        except Exception:
            return False


# ============ 连接器注册表 ============
CONNECTOR_TYPES = {
    "csv": CSVConnector,
    "xlsx": XLSXConnector,
    "internal_api": InternalAPIConnector,
    "third_party": ThirdPartyConnector,
}


def create_connector(data_source: "DataSource") -> BaseConnector:
    """根据 data_source 配置创建连接器实例"""
    from app.db.models import DataSource
    cls = CONNECTOR_TYPES.get(data_source.type)
    if not cls:
        raise ValueError(f"unknown connector type: {data_source.type}")
    meta = ConnectorMetadata(
        source_id=str(data_source.id),
        source_name=data_source.name,
        source_type=data_source.type,
        authorization_note=data_source.authorization_note,
    )
    config = data_source.config_ref or {}
    # 不同类型不同构造参数
    if cls in (CSVConnector, XLSXConnector):
        return cls(meta, file_path=config.get("file_path", ""))
    elif cls == InternalAPIConnector:
        return cls(meta, api_url=config.get("api_url", ""), api_key=config.get("api_key", ""))
    elif cls == ThirdPartyConnector:
        return cls(meta, api_url=config.get("api_url", ""), vendor=config.get("vendor", "unknown"))

    # 尝试通用 HTTP API 连接器
    from app.services.http_api_connector import HttpApiConnector, HttpApiConfig
    if data_source.type == "http_api":
        http_config = HttpApiConfig(
            url=config.get("url", ""),
            method=config.get("method", "GET"),
            auth_type=config.get("auth_type", "none"),
            auth_token=config.get("auth_token", ""),
            auth_username=config.get("auth_username", ""),
            auth_password=config.get("auth_password", ""),
            auth_apikey_header=config.get("auth_apikey_header", "X-Api-Key"),
            headers=config.get("headers", {}),
            pagination_type=config.get("pagination_type", "none"),
            page_size=config.get("page_size", 100),
            page_param=config.get("page_param", "page"),
            offset_param=config.get("offset_param", "offset"),
            cursor_param=config.get("cursor_param", "cursor"),
            max_pages=config.get("max_pages", 50),
            items_path=config.get("items_path", "items"),
            mapping=config.get("mapping", {}),
        )
        return HttpApiConnector(meta, http_config)

    raise ValueError(f"unknown connector config for {data_source.type}")


# ============ 统一入口 ============
def fetch_candidates(data_source: "DataSource") -> Iterator[dict]:
    """从任意数据源拉取候选商品 — 统一接口"""
    connector = create_connector(data_source)
    if not connector.health_check():
        raise RuntimeError(f"connector {data_source.name} health check failed")
    return connector.fetch()