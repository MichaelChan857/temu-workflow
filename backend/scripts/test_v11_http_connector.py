"""V1.1-A1 HTTP API 连接器测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.http_api_connector import (
    HttpApiConfig, HttpApiConnector,
    InternalProductLibrary, Alibaba1688Connector,
)
from app.services.connectors import ConnectorMetadata


def test_config_creation():
    print("[1/4] 配置对象创建")
    config = HttpApiConfig(
        url="https://example.com/api/products",
        auth_type="bearer",
        auth_token="abc123",
        pagination_type="page",
        page_size=50,
    )
    assert config.url == "https://example.com/api/products"
    assert config.auth_type == "bearer"
    assert config.page_size == 50
    print(f"  [OK] 配置正确")


def test_internal_product_library():
    print("\n[2/4] 内部商品库预设")
    meta = ConnectorMetadata(source_id="1", source_name="内部", source_type="http_api")
    conn = InternalProductLibrary(meta, "http://internal:8080", api_key="token123")
    assert conn.config.url.endswith("/api/v1/products")
    assert conn.config.auth_type == "bearer"
    assert conn.config.auth_token == "token123"
    assert conn.config.pagination_type == "page"
    # 字段映射
    assert conn.config.mapping["title"] == "title"
    assert conn.config.mapping["source_product_id"] == "product_id"
    print(f"  [OK] URL: {conn.config.url}")
    print(f"  [OK] 映射字段: {len(conn.config.mapping)} 个")


def test_1688_connector():
    print("\n[3/4] 1688 预设")
    meta = ConnectorMetadata(source_id="2", source_name="1688", source_type="third_party")
    conn = Alibaba1688Connector(meta, app_key="ak", app_secret="as")
    assert "1688.com" in conn.config.url
    assert conn.config.mapping["supplier_sku"] == "productId"
    print(f"  [OK] 1688 URL: {conn.config.url}")


def test_field_mapping():
    print("\n[4/4] 字段映射")
    config = HttpApiConfig(
        url="https://api.example.com/items",
        mapping={"title": "product_name", "price": "sale_price"}
    )
    meta = ConnectorMetadata(source_id="3", source_name="test", source_type="http_api")
    conn = HttpApiConnector(meta, config)
    raw = {"product_name": "Test Item", "sale_price": 19.99, "other_field": "ignore"}
    mapped = conn._map_item(raw)
    assert mapped["title"] == "Test Item"
    assert mapped["price"] == 19.99
    assert "other_field" not in mapped  # 未映射的字段丢弃
    print(f"  [OK] 映射结果: {mapped}")


def main():
    print("=" * 60)
    print("V1.1-A1 HTTP API 连接器测试")
    print("=" * 60)
    test_config_creation()
    test_internal_product_library()
    test_1688_connector()
    test_field_mapping()
    print("\n" + "=" * 60)
    print("全部 V1.1-A1 测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()