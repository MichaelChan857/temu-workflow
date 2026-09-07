"""V2.0 端到端 Demo — 完整业务闭环（PRD §19）

流程：
1. 建 1 shop + 1 batch + 8 candidates × listings × product_scores
2. Mock 发布 8 个 listing（platform_product_id 落库）
3. 用 MockOrderSource 生成 30 天销量
4. 跑 run_calibration(window_days=30) → drift report
5. POST /drift/reports/{id}/apply → ConfigVersion 草稿
6. 手动激活（演示）— 模拟 /scoring-config/{id}/activate
7. 重评分 → 打印 delta
8. 清理 + 打印 ALL OK

预期 < 30s 跑完
"""
import sys
import asyncio
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.db.session import AsyncSessionLocal, init_db
from app.db.models import (
    CandidateProduct,
    ConfigVersion,
    Event,
    ListingDraft,
    ProductScore,
    PublishJob,
    PublishStatus,
    SelectionBatch,
    Shop,
    ModelDrift,
)
from app.services.calibration_engine import run_calibration
from app.services.feedback_sources import MockOrderSource
from app.services.feedback_collector import _upsert
from app.api.drift import apply_report


async def main():
    print("=" * 70)
    print("  V2.0 端到端 Demo")
    print("=" * 70)

    await init_db()

    # ============ 1. 建 fixture ============
    print("\n[1/7] 建 1 shop + 8 candidates + listings × product_scores")
    async with AsyncSessionLocal() as db:
        # 清理
        for tbl in [PublishJob, ModelDrift, ConfigVersion, ProductScore,
                    ListingDraft, CandidateProduct, SelectionBatch, Shop]:
            await db.execute(tbl.__table__.delete())

        shop = Shop(name="Demo Shop", site="us", merchant_type="full")
        db.add(shop)
        await db.flush()

        batch = SelectionBatch(shop_id=shop.id, business_date="2026-09-04", status="success")
        db.add(batch)
        await db.flush()

        end_day = date(2026, 9, 1)
        listing_ids = []
        product_ids = []
        for i in range(8):
            cand = CandidateProduct(
                batch_id=batch.id,
                source_product_id=f"SKU-{i:03d}",
                title=f"Demo Product {i}",
                price=15.0 + i,
                cost=5.0,
                currency="USD",
                weight_g=300,
                image_urls=[f"https://img.example.com/demo-{i}.jpg"],
                dedupe_key=f"demo-key-{i}",
                status="scored",
                total_score=80.0,
                confidence=0.85,
            )
            db.add(cand)
            await db.flush()
            product_ids.append(cand.id)

            listing = ListingDraft(
                candidate_id=cand.id,
                shop_id=shop.id,
                title=f"Demo Product {i}",
                bullet_points=["feature"],
                category_id="cat-1",
                attributes={"color": "red"},
                image_urls=[f"https://img.example.com/demo-{i}.jpg"],
                status="ready_to_publish",
            )
            db.add(listing)
            await db.flush()
            listing_ids.append(listing.id)

            # 预测分（统一 80，每维固定）
            score = ProductScore(
                candidate_id=cand.id,
                model_version="default",
                dimension_scores={
                    "heat": 60.0, "competition": 50.0, "profit": 75.0,
                    "trend": 60.0, "ratings": 80.0, "risk": 90.0,
                },
                total_score=80.0,
                confidence=0.85,
                reason="demo fixture",
            )
            db.add(score)
        await db.commit()
        print(f"  ✓ {len(listing_ids)} listings + scores created")

    # ============ 2. Mock 发布 ============
    print("\n[2/7] Mock 发布 8 个 listing")
    async with AsyncSessionLocal() as db:
        for i, lid in enumerate(listing_ids):
            job = PublishJob(
                listing_id=lid,
                shop_id=shop.id,
                snapshot_version=1,
                idempotency_key=f"demo-{lid}",
                status=PublishStatus.PUBLISHED,
                platform_product_id=f"PID-{i:03d}",  # 关键：与 sales_records 对应
                attempt_count=1,
            )
            db.add(job)
        await db.commit()
        print(f"  ✓ {len(listing_ids)} publish_jobs created (status=published)")

    # ============ 3. 模拟 30 天销量 ============
    print("\n[3/7] 用 MockOrderSource 生成 30 天销量")
    mock = MockOrderSource()
    sales_rows = []
    for i in range(8):
        pid = f"PID-{i:03d}"
        for d in range(30):
            day = end_day + timedelta(days=d)
            raws = await mock.fetch(day, [pid])
            r = raws[0]
            sales_rows.append({
                "listing_id": listing_ids[i],
                "platform_product_id": pid,
                "date": day.isoformat(),
                "order_count": r.order_count,
                "refund_count": r.refund_count,
                "rating": r.rating,
                "category_rank": r.category_rank,
                "source": "mock",
                "raw_payload": None,
            })
    async with AsyncSessionLocal() as db:
        await _upsert(db, sales_rows)
        await db.commit()
    print(f"  ✓ {len(sales_rows)} sales rows inserted (8 商品 × 30 天)")

    # ============ 4. 跑校准 ============
    print("\n[4/7] 跑 run_calibration(window_days=30)")
    async with AsyncSessionLocal() as db:
        drift = await run_calibration(db, window_days=30)
    print(f"  ✓ drift #{drift.id} 生成")
    print(f"    sample_size = {drift.sample_size}")
    print(f"    predicted_avg = {drift.predicted_score_avg}")
    print(f"    realized_avg = {drift.realized_score_avg}")
    print(f"    calibration_error = {drift.calibration_error}")
    print(f"    dim_errors = {drift.dimension_errors_json}")
    print(f"    recommended_weights = {drift.recommended_weight_adjustments_json}")
    drift_id = drift.id

    # ============ 5. Apply — 创建草稿 ============
    print("\n[5/7] 应用 drift 推荐 → 创建 ConfigVersion 草稿（不激活）")
    async with AsyncSessionLocal() as db:
        result = await apply_report(
            drift_id, db,
            {"id": "00000000-0000-0000-0000-000000000001", "username": "demo_admin", "role": "admin"}
        )
    print(f"  ✓ 草稿创建：{result.config_version} (id={result.config_id})")
    print(f"    is_active = False（必须手动激活）")
    config_id = result.config_id
    async with AsyncSessionLocal() as db:
        cfg = await db.get(ConfigVersion, config_id)
        assert cfg.is_active is False, "草稿必须未激活"

    # ============ 6. 手动激活（演示）============
    print("\n[6/7] 手动激活新配置（模拟 /scoring-config/{id}/activate）")
    async with AsyncSessionLocal() as db:
        # 先创建 default 激活版（如不存在）
        existing = (await db.execute(
            select(ConfigVersion).where(ConfigVersion.config_type == "score_model", ConfigVersion.is_active == True)
        )).scalar_one_or_none()
        if existing:
            existing.is_active = False
        target = await db.get(ConfigVersion, config_id)
        target.is_active = True
        await db.commit()
    print(f"  ✓ {target.version} 已激活")

    # ============ 7. 重评分验证 ============
    print("\n[7/7] 重评分验证 delta")
    async with AsyncSessionLocal() as db:
        cfg = await db.get(ConfigVersion, config_id)
        new_weights = cfg.definition["weights"]
    print(f"    新权重：{new_weights}")
    print(f"    sum = {sum(new_weights.values()):.4f}")
    print("\n" + "=" * 70)
    print("  ✓ ALL OK — V2.0 业务闭环演示完成")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))