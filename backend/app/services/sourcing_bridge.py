"""与 temu-product-sourcing 的 schema 转换器 — V1.1-C

把上游选品工具的候选 schema → 我们后端的导入 schema

上游（temu-product-sourcing/references/candidate-schema.md）：
  - title / category / product_url / image_url / price
  - visible_sold_count / review_count / earliest_review_date / earliest_review_status
  - evidence_url / observed_at / collection_status / notes
  - decision / freshness_status / reason_codes（验证后追加）

我们后端（FILE_COLUMNS in import_csv.py）：
  - source_product_id / title / description / brand / category
  - price / cost / currency / weight_g / length_cm / width_cm / height_cm
  - image_url_1 / image_url_2 / image_url_3 / supplier_sku / source_url

核心差异：
  - 上游不带 cost / weight / dimensions / brand
  - 上游带销量/评分证据（但不可作为承诺事实）
"""
from typing import Optional
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SourcingRow:
    """上游选品工具的一行候选"""
    title: str
    category: str
    product_url: str
    image_url: Optional[str]
    price: Optional[str]  # 带货币的字符串
    visible_sold_count: Optional[int]
    review_count: Optional[int]
    earliest_review_date: Optional[str]
    earliest_review_status: Optional[str]
    evidence_url: Optional[str]
    observed_at: Optional[str]
    collection_status: Optional[str]
    notes: Optional[str]
    decision: Optional[str] = None
    freshness_status: Optional[str] = None
    reason_codes: Optional[str] = None


def convert_to_internal(row: SourcingRow) -> dict:
    """把上游 SourcingRow 转为我们后端的 CSV 行 dict

    映射规则：
      - product_url → source_url（参考链接）+ source_product_id（URL 末段）
      - title → title
      - category → category
      - image_url → image_url_1
      - price → price（去除货币符号）
      - visible_sold_count / review_count → 不带入（不作为承诺事实）
      - earliest_review_date → 写入 notes（信息保留）
      - decision='eligible' → 强制重评分（不直接信任上游判定）
    """
    # 提取 source_product_id（从 URL 末段）
    source_product_id = row.product_url.rstrip("/").split("/")[-1] if row.product_url else ""

    # 解析 price（去除货币符号）
    price = None
    if row.price:
        # 常见格式："$19.99" / "19.99 USD" / "USD 19.99"
        cleaned = "".join(c for c in row.price if c.isdigit() or c == ".")
        try:
            price = float(cleaned)
        except ValueError:
            price = None

    # currency（从 price 提取）
    currency = "USD"  # 默认
    if row.price:
        upper = row.price.upper()
        # 符号先识别（避免 EUR 在 upper 中找不到）
        if "€" in row.price or "EUR" in upper:
            currency = "EUR"
        elif "£" in row.price or "GBP" in upper:
            currency = "GBP"
        elif "¥" in row.price or "￥" in row.price or "CNY" in upper:
            currency = "CNY"
        elif "USD" in upper or "$" in row.price:
            currency = "USD"

    # supplier_sku（无 → 用 URL 末段）
    supplier_sku = source_product_id or "SOURCING"

    # 把上游证据数据写进 notes（后端可读但不作为承诺事实）
    evidence_note_parts = []
    if row.visible_sold_count is not None:
        evidence_note_parts.append(f"sold:{row.visible_sold_count}")
    if row.review_count is not None:
        evidence_note_parts.append(f"reviews:{row.review_count}")
    if row.earliest_review_date:
        evidence_note_parts.append(f"first_review:{row.earliest_review_date}")
    if row.evidence_url:
        evidence_note_parts.append(f"src:{row.evidence_url}")
    if row.notes:
        evidence_note_parts.append(f"note:{row.notes}")

    note = "; ".join(evidence_note_parts)
    # 注：description 字段携带证据信息（MVP 阶段简化）
    description = note or f"imported from temu-product-sourcing ({row.observed_at or 'unknown'})"

    return {
        "source_product_id": source_product_id,
        "title": row.title,
        "description": description,
        "brand": "",  # 上游无 brand，留空 → 评分会扣分
        "category": row.category,
        "price": price or 0,
        "cost": None,  # 上游无 cost
        "currency": currency,
        "weight_g": None,
        "length_cm": None,
        "width_cm": None,
        "height_cm": None,
        "image_url_1": row.image_url or "",
        "image_url_2": "",
        "image_url_3": "",
        "supplier_sku": supplier_sku,
        "source_url": row.product_url,
        # 元数据（不直接进入候选商品，但写 events）
        "_metadata": {
            "visible_sold_count": row.visible_sold_count,
            "review_count": row.review_count,
            "earliest_review_date": row.earliest_review_date,
            "earliest_review_status": row.earliest_review_status,
            "upstream_decision": row.decision,
            "upstream_freshness": row.freshness_status,
            "upstream_reason_codes": row.reason_codes,
        },
    }


def filter_eligible(rows: list[SourcingRow]) -> list[SourcingRow]:
    """只保留上游判定为 eligible 的行

    注：上游 'hold' 和 'rejected' 直接丢弃（避免污染）
    """
    return [r for r in rows if r.decision == "eligible"]


# ============ 上游数据接入示例（端到端集成）============
def ingest_sourcing_csv_to_backend(
    csv_path: str,
    api_base: str = "http://localhost:8000",
    auth_token: str = "",
) -> dict:
    """读取上游 CSV → 转换 → 调用后端 /api/v1/import/file

    MVP 实现：客户运行 `temu-product-sourcing` 工具后，导出 candidates.csv，
    再用此脚本批量导入我们的系统。
    """
    import csv
    import httpx

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [SourcingRow(**{k: (v if v != "" else None) for k, v in r.items()}) for r in reader]

    eligible = filter_eligible(rows)
    internal_rows = [convert_to_internal(r) for r in eligible]

    # 调后端 /import/json（JSON 模式，不写 CSV 文件）
    candidates = []
    for ir in internal_rows:
        meta = ir.pop("_metadata", {})
        candidates.append({
            "source_product_id": ir["source_product_id"],
            "title": ir["title"],
            "description": ir["description"],
            "category": ir["category"],
            "price": ir["price"] or 0,
            "currency": ir["currency"],
            "image_urls": [ir["image_url_1"]] if ir["image_url_1"] else [],
            "supplier_sku": ir["supplier_sku"],
            "source_url": ir["source_url"],
        })

    if not candidates:
        return {"status": "no_eligible", "in": len(rows), "out": 0}

    resp = httpx.post(
        f"{api_base}/api/v1/import/json",
        json={"candidates": candidates},
        headers={"Authorization": f"Bearer {auth_token}"} if auth_token else {},
        timeout=60.0,
    )
    resp.raise_for_status()
    result = resp.json()
    return {
        "status": "imported",
        "upstream_total": len(rows),
        "upstream_eligible": len(eligible),
        "backend_result": result,
    }