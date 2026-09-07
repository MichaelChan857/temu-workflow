"""V1.1-C 上游选品工具集成测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.sourcing_bridge import (
    SourcingRow, convert_to_internal, filter_eligible, ingest_sourcing_csv_to_backend
)


def test_basic_conversion():
    print("[1/4] 基本字段转换")
    row = SourcingRow(
        title="Pet Interactive Toy",
        category="Pet",
        product_url="https://temu.com/g-6056689.html",
        image_url="https://img.kwcdn.com/product/abc.jpg",
        price="$19.99",
        visible_sold_count=1500,
        review_count=15,
        earliest_review_date="2026-08-15",
        earliest_review_status="verified",
        evidence_url="https://temu.com/g-6056689.html",
        observed_at="2026-09-02T13:00:00Z",
        collection_status=None,
        notes="Best seller in pet toys",
        decision="eligible",
        freshness_status="within_window_inferred",
        reason_codes=None,
    )

    internal = convert_to_internal(row)
    assert internal["title"] == "Pet Interactive Toy"
    assert internal["price"] == 19.99
    assert internal["currency"] == "USD"
    assert internal["source_product_id"] == "g-6056689.html"
    assert internal["image_url_1"] == "https://img.kwcdn.com/product/abc.jpg"
    assert internal["source_url"] == "https://temu.com/g-6056689.html"
    # 销量证据不直接进数据，留在 description
    assert "1500" in internal["description"]
    assert "verified" in internal["description"] or "2026-08-15" in internal["description"]
    # cost/weight 为 None（上游无）
    assert internal["brand"] == ""
    print(f"  [OK] price {row.price} → {internal['price']} {internal['currency']}")
    print(f"  [OK] description 含证据：{internal['description'][:80]}...")


def test_filter_eligible():
    print("\n[2/4] 过滤 eligible 行")
    rows = [
        SourcingRow(title="A", category="X", product_url="", image_url=None, price=None,
                    visible_sold_count=None, review_count=None, earliest_review_date=None,
                    earliest_review_status=None, evidence_url=None, observed_at=None,
                    collection_status=None, notes=None, decision="eligible"),
        SourcingRow(title="B", category="X", product_url="", image_url=None, price=None,
                    visible_sold_count=None, review_count=None, earliest_review_date=None,
                    earliest_review_status=None, evidence_url=None, observed_at=None,
                    collection_status=None, notes=None, decision="hold"),
        SourcingRow(title="C", category="X", product_url="", image_url=None, price=None,
                    visible_sold_count=None, review_count=None, earliest_review_date=None,
                    earliest_review_status=None, evidence_url=None, observed_at=None,
                    collection_status=None, notes=None, decision="rejected"),
    ]
    eligible = filter_eligible(rows)
    assert len(eligible) == 1
    assert eligible[0].title == "A"
    print(f"  [OK] 3 行过滤后剩 1 行 eligible")


def test_currency_parsing():
    print("\n[3/4] 多货币解析")
    cases = [
        ("$19.99", 19.99, "USD"),
        ("€25.00", 25.0, "EUR"),
        ("19.99 USD", 19.99, "USD"),
        ("¥199.00", 199.0, "CNY"),
    ]
    for price_str, expected_price, expected_currency in cases:
        row = SourcingRow(
            title="X", category="X", product_url="", image_url=None, price=price_str,
            visible_sold_count=None, review_count=None, earliest_review_date=None,
            earliest_review_status=None, evidence_url=None, observed_at=None,
            collection_status=None, notes=None, decision="eligible",
        )
        internal = convert_to_internal(row)
        assert internal["price"] == expected_price, f"price {price_str!r} -> {internal['price']}"
        assert internal["currency"] == expected_currency, f"currency {price_str!r} -> {internal['currency']}"
        print(f"  [OK] {price_str!r} -> {internal['price']} {internal['currency']}".encode("ascii", "replace").decode("ascii"))


def test_brand_and_cost_handling():
    print("\n[4/4] brand/cost 缺省处理")
    row = SourcingRow(
        title="X", category="X", product_url="", image_url=None, price="$10",
        visible_sold_count=None, review_count=None, earliest_review_date=None,
        earliest_review_status=None, evidence_url=None, observed_at=None,
        collection_status=None, notes=None, decision="eligible",
    )
    internal = convert_to_internal(row)
    assert internal["brand"] == ""  # 上游无 brand → 评分会扣分
    assert internal["cost"] is None
    print(f"  [OK] brand='{internal['brand']}'（空 → 评分扣分）, cost={internal['cost']}（未知）")


def main():
    print("=" * 60)
    print("V1.1-C 上游选品工具集成测试")
    print("=" * 60)
    test_basic_conversion()
    test_filter_eligible()
    test_currency_parsing()
    test_brand_and_cost_handling()
    print("\n" + "=" * 60)
    print("全部 V1.1-C 测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()