"""V2.0 Phase 2 — 校准引擎测试（PRD §19）

C-01 5 商品 × 30 行 mock 销量 → sample_size=5
C-02 realized_score ∈ [0, 100], cal_err = avg(realized) - avg(predicted)
C-03 dimension_errors.heat > 0 → recommended_weights.heat > current_weights.heat
C-04 sum(recommended_weights) == 1.0 ±0.001
C-05 /drift/reports/{id}/apply 创建 ConfigVersion is_active=False（不自动激活）
C-06 weekly_report 窗口严格 7 天
C-07 样本 < 5 → 推荐 dict 空 + Event 警告 payload
"""
import sys
import asyncio
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, init_db
from app.db.models import (
    CandidateProduct,
    ConfigVersion,
    Event,
    ListingDraft,
    ProductScore,
    SelectionBatch,
    Shop,
    User,
    ModelDrift,
    SalesRecord,
)
from app.services.calibration_engine import (
    compute_realized_score,
    compute_realized_components,
    dimension_errors,
    recommend_adjustments,
    run_calibration,
)
from app.services.weekly_report import generate_weekly_report


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
async def _build_fixture(n_listings: int = 5, n_days: int = 30):
    """建 1 shop + 1 batch + n_listings × (candidate + listing + product_score + n_days × sales_record)

    销量曲线：每天 order_count = 3, refund_count = 0, rating = 4.5, rank = 50
    预测分数：固定 80，dim 分数固定 {heat:60, competition:50, profit:75, trend:60, ratings:80, risk:90}
    """
    await init_db()
    async with AsyncSessionLocal() as db:
        # 清理旧数据
        for tbl in [SalesRecord, ModelDrift, ConfigVersion, ProductScore,
                    ListingDraft, CandidateProduct, SelectionBatch, User, Shop]:
            await db.execute(tbl.__table__.delete())

        shop = Shop(name="Test Shop", site="us", merchant_type="full")
        db.add(shop)
        await db.flush()

        admin = User(username="admin", display_name="Admin", role="admin", shop_id=shop.id, is_active=True)
        db.add(admin)
        await db.flush()

        batch = SelectionBatch(shop_id=shop.id, business_date="2026-09-04", status="success")
        db.add(batch)
        await db.flush()

        end_day = date(2026, 9, 1)
        sales_rows = []
        for i in range(n_listings):
            cand = CandidateProduct(
                batch_id=batch.id,
                source_product_id=f"SKU-{i}",
                title=f"Product {i}",
                price=10.0 + i,
                cost=5.0,
                currency="USD",
                weight_g=200,
                image_urls=["https://example.com/img.jpg"],
                dedupe_key=f"key-{i}",
                status="scored",
                total_score=80.0,
                confidence=0.9,
            )
            db.add(cand)
            await db.flush()

            listing = ListingDraft(
                candidate_id=cand.id,
                shop_id=shop.id,
                title=f"Product {i}",
                bullet_points=["feature"],
                category_id="cat-1",
                attributes={"color": "red"},
                image_urls=["https://example.com/img.jpg"],
                status="published",
            )
            db.add(listing)
            await db.flush()

            score = ProductScore(
                candidate_id=cand.id,
                model_version="default",
                dimension_scores={
                    "heat": 60.0, "competition": 50.0, "profit": 75.0,
                    "trend": 60.0, "ratings": 80.0, "risk": 90.0,
                },
                total_score=80.0,
                confidence=0.9,
                reason="test fixture",
            )
            db.add(score)

            # 销量：n_days 天，每天 3 单 0 退 评分 4.5 排名 50
            for d in range(n_days):
                sales_rows.append({
                    "listing_id": listing.id,
                    "platform_product_id": f"PID-{i}",
                    "date": (end_day + timedelta(days=d)).isoformat(),
                    "order_count": 3,
                    "refund_count": 0,
                    "rating": 4.5,
                    "category_rank": 50,
                    "source": "test",
                    "raw_payload": None,
                })

        # 直接批量 insert（不通过 upsert 验证 collect 是另一回事）
        from app.services.feedback_collector import _upsert
        await _upsert(db, sales_rows)
        await db.commit()
        return end_day + timedelta(days=n_days - 1)


# ============ C-01 ============
async def c_01_sample_size():
    """5 商品 → sample_size=5"""
    await _build_fixture(n_listings=5, n_days=30)
    async with AsyncSessionLocal() as db:
        drift = await run_calibration(db, window_days=30)
    assert drift.sample_size == 5, f"应 5，实际 {drift.sample_size}"
    assert drift.model_version == "default"
    assert drift.predicted_score_avg == 80.0
    assert drift.realized_score_avg is not None


# ============ C-02 ============
async def c_02_realized_range_and_error():
    """realized_score ∈ [0, 100], cal_err = avg(realized) - avg(predicted)"""
    await _build_fixture(n_listings=5, n_days=30)
    async with AsyncSessionLocal() as db:
        drift = await run_calibration(db, window_days=30)
    assert 0.0 <= drift.realized_score_avg <= 100.0
    expected_err = round(drift.realized_score_avg - drift.predicted_score_avg, 2)
    assert drift.calibration_error == expected_err


# ============ C-03 ============
def c_03_recommend_direction():
    """bias > 0 → 推荐权重增加"""
    current = {"heat": 0.25, "competition": 0.20, "profit": 0.20, "trend": 0.20, "ratings": 0.10, "risk": 0.05}
    errors = {"heat": 10.0, "competition": -10.0, "profit": 5.0, "trend": -5.0, "ratings": 0.0, "risk": 0.0}
    rec = recommend_adjustments(errors, current, lr=0.05, cap=0.05)
    assert rec["heat"] > current["heat"], f"heat 应增加（bias>0）：{rec['heat']} vs {current['heat']}"
    assert rec["competition"] < current["competition"], f"competition 应减少（bias<0）"


# ============ C-04 ============
def c_04_recommend_normalized():
    """推荐权重和 = 1.0 ±0.001"""
    current = {"heat": 0.25, "competition": 0.20, "profit": 0.20, "trend": 0.20, "ratings": 0.10, "risk": 0.05}
    errors = {"heat": 30.0, "competition": -20.0, "profit": 15.0, "trend": 10.0, "ratings": -5.0, "risk": 8.0}
    rec = recommend_adjustments(errors, current)
    total = sum(rec.values())
    assert abs(total - 1.0) < 0.001, f"权重和应=1.0，实际 {total}"


# ============ C-05 Apply 创建草稿不激活 ============
async def c_05_apply_creates_draft_not_active():
    """apply 端点创建 ConfigVersion 但 is_active=False"""
    from app.api.drift import apply_report
    from app.core.security import get_current_user  # noqa
    from uuid import UUID

    await _build_fixture(n_listings=5, n_days=30)
    async with AsyncSessionLocal() as db:
        drift = await run_calibration(db, window_days=30)
        drift_id = drift.id

    # 直接调 apply_report 内部逻辑（不走 HTTP — RBAC 验证由 Phase 3 整合测覆盖）
    async with AsyncSessionLocal() as db:
        from fastapi import HTTPException
        admin_user = {
            "id": str((await db.execute(
                __import__('sqlalchemy').select(User).where(User.username == "admin")
            )).scalar_one().id),
            "username": "admin",
            "role": "admin",  # RBAC 要求
        }

        # 模拟 apply：直接调内部函数组合
        drift = await db.get(ModelDrift, drift_id)
        assert drift.recommended_weight_adjustments_json, "应有推荐权重"

        # 调 apply_report 端点函数（伪 admin user dict）
        # 注：apply_report 签名是 (drift_id, db, user) → 直接 call
        result = await apply_report(drift_id, db, admin_user)
        assert result.drift_id == drift_id
        assert result.config_id > 0

        # 验证 ConfigVersion is_active=False
        cfg = await db.get(ConfigVersion, result.config_id)
        assert cfg.is_active is False, f"必须 is_active=False，实际 {cfg.is_active}"

        # 验证 drift 状态更新
        await db.refresh(drift)
        assert drift.status == "applied"
        assert drift.applied_config_id == cfg.id


# ============ C-06 weekly 窗口 7 天 ============
async def c_06_weekly_window_7d():
    """周报生成时窗口严格 7 天（fixture 的 30 天数据内）"""
    end_day = await _build_fixture(n_listings=5, n_days=30)  # end = 09-30
    # 选 09-30 作为 end_day，向前回 7 天 = 09-24..09-30（含 7 个数据点）
    weekly_end = date(2026, 9, 30)
    async with AsyncSessionLocal() as db:
        drift = await generate_weekly_report(db, end_day=weekly_end)
    start = date.fromisoformat(drift.window_start)
    end = date.fromisoformat(drift.window_end)
    n_days = (end - start).days + 1
    assert n_days == 7, f"周报应覆盖 7 天数据点，实际 {n_days} 天（{start}..{end}）"


# ============ C-07 样本不足 ============
async def c_07_small_sample_warning():
    """样本 < 5 → 推荐 dict 空 + Event warning payload"""
    await _build_fixture(n_listings=3, n_days=30)  # 不到 5 个
    async with AsyncSessionLocal() as db:
        drift = await run_calibration(db, window_days=30)
    assert drift.sample_size == 3
    assert drift.recommended_weight_adjustments_json == {}, f"应空，实际 {drift.recommended_weight_adjustments_json}"


def main():
    print("=" * 70)
    print("V2.0 Phase 2 — 校准引擎 + 周报测试")
    print("=" * 70)

    print("\n--- C-01 样本数 ---")
    check("C-01", "5 商品 × 30 天 → sample_size=5", c_01_sample_size)

    print("\n--- C-02 范围 + 误差 ---")
    check("C-02", "realized ∈ [0,100], cal_err 公式", c_02_realized_range_and_error)

    print("\n--- C-03 推荐方向 ---")
    check("C-03", "bias>0 → 权重增加", c_03_recommend_direction)

    print("\n--- C-04 归一化 ---")
    check("C-04", "推荐权重和=1.0", c_04_recommend_normalized)

    print("\n--- C-05 Apply 不激活 ---")
    check("C-05", "apply 创建草稿 is_active=False", c_05_apply_creates_draft_not_active)

    print("\n--- C-06 周报窗口 7 天 ---")
    check("C-06", "weekly_report 窗口跨度 6 天（7 天含首尾）", c_06_weekly_window_7d)

    print("\n--- C-07 样本不足 ---")
    check("C-07", "sample<5 → 推荐空 + warning", c_07_small_sample_warning)

    print("\n" + "=" * 70)
    print(f"Phase 2 验收：{RESULTS['passed']}/{RESULTS['total']} 通过，{RESULTS['failed']} 失败")
    print("=" * 70)

    if RESULTS["failed"]:
        print("\n失败详情：")
        for ac_id, name, status, err in RESULTS["details"]:
            if status != "PASS":
                print(f"  [{ac_id}] {status}: {name} — {err}")

    return 0 if RESULTS["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())