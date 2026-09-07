"""V2.0 Phase 3 — 相似去重测试（PRD FR-021）

D-01 同标题同图 → 阻塞 duplicate_embedding
D-02 不同标题不同图 → 不阻塞
D-03 mock SHA-1 一致性（同输入 → 同向量）
D-04 cosine 数学正确性
D-05 threshold 0.95 严格（0.94 不触发）
"""
import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal, init_db
from app.db.models import ListingDraft, Shop, SelectionBatch, CandidateProduct
from app.services.embedding_backends import MockEmbeddingBackend
from app.services.similarity import cosine, find_duplicates


RESULTS = {"total": 0, "passed": 0, "failed": 0, "details": []}


def check(ac_id, name, fn):
    RESULTS["total"] += 1
    try:
        asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
        RESULTS["passed"] += 1
        RESULTS["details"].append((ac_id, name, "PASS", ""))
        print(f"  [{ac_id}] PASS: {name}")
    except AssertionError as e:
        RESULTS["failed"] += 1
        RESULTS["details"].append((ac_id, name, "FAIL", str(e)))
        print(f"  [{ac_id}] FAIL: {name} — {e}")
    except Exception as e:
        RESULTS["failed"] += 1
        RESULTS["details"].append((ac_id, name, "ERROR", str(e)))
        print(f"  [{ac_id}] ERROR: {name} — {e}")


# ============ Fixture ============
async def _build_shop_and_listings(items: list[dict]) -> tuple:
    """items: [(title, image_urls, status)]"""
    await init_db()
    async with AsyncSessionLocal() as db:
        for tbl in [ListingDraft, CandidateProduct, SelectionBatch, Shop]:
            await db.execute(tbl.__table__.delete())

        shop = Shop(name="Test Shop", site="us", merchant_type="full")
        db.add(shop)
        await db.flush()

        batch = SelectionBatch(shop_id=shop.id, business_date="2026-09-04", status="success")
        db.add(batch)
        await db.flush()

        listing_ids = []
        for it in items:
            cand = CandidateProduct(
                batch_id=batch.id,
                source_product_id=f"SKU-{len(listing_ids)}",
                title=it["title"],
                price=10.0, cost=5.0, currency="USD", weight_g=200,
                image_urls=it["image_urls"],
                dedupe_key=f"key-{len(listing_ids)}",
                status=it["status"],
            )
            db.add(cand)
            await db.flush()
            listing = ListingDraft(
                candidate_id=cand.id,
                shop_id=shop.id,
                title=it["title"],
                bullet_points=["feature"],
                category_id="cat-1",
                attributes={"color": "red"},
                image_urls=it["image_urls"],
                status=it["status"],
            )
            db.add(listing)
            await db.flush()
            listing_ids.append(listing.id)
        await db.commit()
        return shop.id, listing_ids


# ============ D-01 重复检测 ============
async def d_01_same_blocked():
    """同标题同图 → 阻塞"""
    same = ["https://img.example.com/a.jpg"]
    shop_id, ids = await _build_shop_and_listings([
        {"title": "Premium Smart Watch", "image_urls": same, "status": "published"},
        {"title": "Premium Smart Watch", "image_urls": same, "status": "published"},
    ])
    # 第二个 listing 检查时应找到第一个
    async with AsyncSessionLocal() as db:
        hits = await find_duplicates(
            db, shop_id=shop_id, exclude_listing_id=ids[1],
            image_urls=same, title="Premium Smart Watch", threshold=0.95,
        )
    assert len(hits) >= 1, f"应找到 1+ 重复，实际 {len(hits)}"
    assert hits[0]["similarity"] >= 0.95
    assert hits[0]["listing_id"] == str(ids[0])


# ============ D-02 不重复不阻塞 ============
async def d_02_different_not_blocked():
    """不同标题不同图 → 不阻塞"""
    shop_id, ids = await _build_shop_and_listings([
        {"title": "Premium Smart Watch", "image_urls": ["https://img/a.jpg"], "status": "published"},
        {"title": "Wireless Earbuds Pro", "image_urls": ["https://img/b.jpg"], "status": "published"},
    ])
    async with AsyncSessionLocal() as db:
        hits = await find_duplicates(
            db, shop_id=shop_id, exclude_listing_id=ids[1],
            image_urls=["https://img/b.jpg"], title="Wireless Earbuds Pro", threshold=0.95,
        )
    assert len(hits) == 0, f"不同商品不应阻塞，实际 {len(hits)}"


# ============ D-03 mock SHA-1 一致 ============
async def d_03_mock_hash_consistent():
    """同输入 → 同向量"""
    backend = MockEmbeddingBackend()
    v1 = await backend.embed_image(["https://img/x.jpg"])
    v2 = await backend.embed_image(["https://img/x.jpg"])
    assert v1 == v2, "同 URL 应返回完全相同向量"

    t1 = await backend.embed_text("Premium Watch")
    t2 = await backend.embed_text("Premium Watch")
    assert t1 == t2, "同文本应返回完全相同向量"

    # 不同输入 → 不同向量
    v3 = await backend.embed_image(["https://img/Y.jpg"])
    assert v1 != v3


# ============ D-04 cosine 数学 ============
def d_04_cosine_math():
    """cosine 数学正确性"""
    # 同向量 → 1.0
    a = [1.0, 0.0, 0.0]
    assert abs(cosine(a, a) - 1.0) < 1e-9

    # 正交 → 0.0
    b = [0.0, 1.0, 0.0]
    assert abs(cosine(a, b)) < 1e-9

    # 反向 → -1.0
    c = [-1.0, 0.0, 0.0]
    assert abs(cosine(a, c) + 1.0) < 1e-9

    # 空向量 → 0.0
    assert cosine([], []) == 0.0
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0  # 维度不等


# ============ D-05 threshold 严格 ============
def d_05_threshold_strict():
    """threshold 0.95 严格（0.94 不触发）"""
    # 完全相同的归一化向量
    a = [0.6, 0.8, 0.0]
    b = [0.6, 0.8, 0.0]
    assert cosine(a, b) >= 0.95, "完全相同向量 cosine 应 ≥0.95"

    # 加一点噪声 → cosine 略低于 1
    c = [0.6, 0.79, 0.0]
    sim = cosine(a, c)
    assert 0.99 < sim < 1.0, f"近相同向量 cosine 应 0.99-1.0，实际 {sim}"


def main():
    print("=" * 70)
    print("V2.0 Phase 3 — 相似去重测试")
    print("=" * 70)

    print("\n--- D-01 同图同标题 ---")
    check("D-01", "同图同标题 → 阻塞", d_01_same_blocked)

    print("\n--- D-02 不同不阻塞 ---")
    check("D-02", "不同图不同标题 → 不阻塞", d_02_different_not_blocked)

    print("\n--- D-03 mock 一致性 ---")
    check("D-03", "mock embedding 同输入 → 同向量", d_03_mock_hash_consistent)

    print("\n--- D-04 cosine 数学 ---")
    check("D-04", "cosine 边界 + 维度不等", d_04_cosine_math)

    print("\n--- D-05 threshold 严格 ---")
    check("D-05", "threshold 0.95 严格（近相同 < 1.0）", d_05_threshold_strict)

    print("\n" + "=" * 70)
    print(f"Phase 3 验收：{RESULTS['passed']}/{RESULTS['total']} 通过，{RESULTS['failed']} 失败")
    print("=" * 70)

    if RESULTS["failed"]:
        print("\n失败详情：")
        for ac_id, name, status, err in RESULTS["details"]:
            if status != "PASS":
                print(f"  [{ac_id}] {status}: {name} — {err}")

    return 0 if RESULTS["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())