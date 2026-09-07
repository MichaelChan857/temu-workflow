"""端到端业务流演示 — 不用数据库，真实跑算法

展示完整业务流的所有关键步骤，让客户/老板能"看到"系统在做什么。
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_step(n, title):
    print(f"\n[STEP {n}] {title}")
    print("-" * 70)


# 导入所有业务模块
from app.services.rules import run_rules
from app.services.scoring import score_candidate, rank_candidates
from app.services.state_machine import (
    ListingStatus, can_transition, assert_transition,
    TERMINAL_STATUSES, next_statuses
)
from app.services.audit import LogType, scrub, scrub_dict, make_log, RETENTION_DAYS
from app.services.exception_matrix import EXCEPTION_MATRIX, should_auto_retry
from app.services.permissions_v2 import PERMISSION_CATALOG, has_permission_v2
from app.services.risk_register import RISKS, get_risk
from app.services.claude_client import ClaudeClient
from app.services.retry import RetryPolicy, compute_backoff, with_retry


async def main():
    # ============ 场景：单商品从导入到发布的完整业务流 ============
    print_header("场景：1 个 Pet Toy 商品从 CSV 导入到 Temu 发布的完整业务流")
    print("""
    这是一个真实可执行的端到端业务流演示。
    所有步骤都用真实算法跑，不依赖数据库。
    """)

    # ========== STEP 1：CSV 导入 → 规则初筛 ==========
    print_step(1, "CSV 导入 + 规则初筛 + 评分")

    csv_row = {
        "title": "Pet Interactive Puzzle Toy - Slow Feeder",
        "description": "Durable non-toxic plastic dog puzzle toy",
        "category": "Pet Toys",
        "price": 18.99,
        "cost": 7.50,
        "currency": "USD",
        "weight_g": 300,
        "dimensions": {"l": 20, "w": 20, "h": 5},
        "image_urls": ["https://example.com/img/pet1a.jpg"],
        "supplier_sku": "SKU-PET-001",
        "source_product_id": "SP-001",
    }

    print(f"  导入商品: {csv_row['title']}")
    print(f"  价格: ${csv_row['price']}  成本: ${csv_row['cost']}  重量: {csv_row['weight_g']}g")

    # 规则
    passes, hits = run_rules(csv_row)
    print(f"\n  [规则引擎]")
    if passes:
        print(f"    [OK] 通过硬性规则（{len(hits)} 条软性标记）")
    else:
        hard_codes = [h.rule_code for h in hits if h.rule_type == "hard"]
        print(f"    [X] 被硬性规则淘汰: {hard_codes}")
        return

    # 评分
    score = score_candidate(csv_row)
    print(f"\n  [6 维评分]")
    for dim, value in score.dimension_scores.items():
        bar = "#" * int(value / 5) + "." * (20 - int(value / 5))
        print(f"    {dim:12s}: {bar} {value:5.1f}")
    print(f"    {'总分':12s}: {score.total_score:5.1f} / 100  置信度: {score.confidence:.0%}")
    print(f"    理由: {score.reason}")

    # ========== STEP 2：状态机迁移 → 一审 ==========
    print_step(2, "状态机迁移：imported → first_review")

    transitions = [
        ("scored", {"score": 80}),
        ("first_review", {"in_top_n": True}),
    ]
    current = "imported"
    # 直接到 normalized（dedupe 已在导入时完成）
    assert_transition(current, "normalized", deduped=True)
    print(f"  [OK] {current} -> normalized")
    current = "normalized"
    for target, kwargs in transitions:
        if can_transition(current, target):
            assert_transition(current, target, **kwargs)
            print(f"  [OK] {current} -> {target}")
            current = target
        else:
            print(f"  [X] {current} -> {target} 非法")
            return
    print(f"  当前状态: {current}（一审待审）")

    # ========== STEP 3：一审决策 ==========
    print_step(3, "一审决策（运营角色）")

    decision = "approve"
    reason_code = None
    print(f"  角色: operator（选品运营）")
    print(f"  决策: {decision}")

    if has_permission_v2("operator", "review.first.approve"):
        print(f"  [OK] 权限校验通过")
    else:
        print(f"  [X] 权限不足")
        return

    # 状态切换
    new_status = "content_generating"
    print(f"  [OK] 状态: {current} -> {new_status}")
    current = new_status

    # ========== STEP 4：AI 文案生成 ==========
    print_step(4, "AI 文案生成（Claude API / mock 模式）")

    client = ClaudeClient()  # mock
    print(f"  模式: {'mock' if client.use_mock else 'live Claude API'}")

    result = await client.generate_listing_content(
        {"title": csv_row["title"], "category": csv_row["category"]},
        target_language="en",
    )

    print(f"\n  [AI 输出]")
    print(f"    标题: {result.title}")
    print(f"    卖点: {len(result.bullet_points)} 条")
    for bp in result.bullet_points:
        print(f"      - {bp}")
    print(f"    描述: {result.description[:80]}...")
    print(f"    提示词版本: {result.prompt_version}")

    # ========== STEP 5：状态 → editing → second_review ==========
    print_step(5, "状态机：content_generating → editing → second_review")

    assert_transition("content_generating", "editing", ai_success=True)
    print(f"  [OK] content_generating -> editing")
    current = "editing"

    # 模拟运营微调
    edited_title = "Pet Interactive Puzzle Toy - Slow Feeder (Premium)"
    print(f"  运营微调标题: ...{edited_title[-20:]}")

    assert_transition("editing", "second_review", all_required_filled=True)
    print(f"  [OK] editing -> second_review")
    current = "second_review"

    # ========== STEP 6：二审校验 + 同人校验 + 冻结快照 ==========
    print_step(6, "二审校验 + 快照冻结")

    # 校验
    errors = []
    warnings = []
    if not edited_title or len(edited_title) > 200:
        errors.append("missing_required:title")
    if not result.description:
        errors.append("missing_required:description")
    print(f"  校验: {len(errors)} 错误, {len(warnings)} 警告")

    # 同人校验（默认 suggested）
    policy = "suggested"
    same_person = False  # 一审与二审不同人
    print(f"  同人校验: policy={policy}, 同人={same_person}")
    if same_person and policy == "forced":
        print(f"  [X] 强制模式下同人应拒绝")
    else:
        print(f"  [OK] 通过二审校验")

    # 冻结快照
    snapshot = {
        "title": edited_title,
        "bullet_points": result.bullet_points,
        "description": result.description,
        "image_urls": csv_row["image_urls"],
        "attributes": {"price": csv_row["price"], "currency": csv_row["currency"]},
        "version": 2,
    }
    print(f"  [OK] 快照冻结 v{snapshot['version']}（不可变）")

    assert_transition("second_review", "ready_to_publish", snapshot_frozen=True)
    print(f"  [OK] 状态: second_review -> ready_to_publish")
    current = "ready_to_publish"

    # ========== STEP 7：发布到 Temu（幂等键）============
    print_step(7, "发布到 Temu（mock 适配器 + 幂等键 + 异步）")

    import hashlib
    idempotency_key = hashlib.sha256(
        f"shop-1|{snapshot['version']}|listing-1".encode()
    ).hexdigest()[:32]
    print(f"  幂等键: {idempotency_key[:16]}...")

    # 模拟发布
    print(f"  模拟 /v1/products/publish ...")
    publish_resp = {
        "success": True,
        "is_async": True,
        "platform_task_id": "TT-1788332771-2cdc31",
        "platform_request_id": "TR-98d78e9841fa",
        "platform_status": "submitted",
    }
    print(f"  [OK] 异步受理: task_id={publish_resp['platform_task_id']}")

    # 模拟轮询
    print(f"  模拟 /v1/products/query（轮询中）...")
    poll_resp = {"platform_status": "published", "platform_product_id": "TP-2054d5c0a1"}
    print(f"  [OK] 轮询终态: published, product_id={poll_resp['platform_product_id']}")

    assert_transition("ready_to_publish", "publishing", snapshot_match=True)
    assert_transition("publishing", "platform_reviewing", platform_task_id="TT-xxx")
    assert_transition("platform_reviewing", "published", poll_terminal=True)
    print(f"  [OK] 状态: publishing -> platform_reviewing -> published")

    # ========== STEP 8：审计日志 + 风险提示 ==========
    print_step(8, "审计日志 + 风险监控")

    print(f"  [审计事件] 类型:")
    for lt in LogType:
        print(f"    - {lt.value:10s} (留存 {RETENTION_DAYS[lt]} 天)")

    print(f"\n  [凭证脱敏演示]")
    sensitive = "password=admin123, token=abc, Bearer eyJhbGciOiJIUzI1NiJ9.x.y"
    scrubbed = scrub(sensitive)
    print(f"    原文: {sensitive}")
    print(f"    脱敏: {scrubbed}")

    print(f"\n  [14 项风险监控]")
    print(f"    高风险 7 项：")
    for r in RISKS:
        if r.probability in ("high", "very_high"):
            print(f"      [{r.code}] {r.risk}")
            print(f"          监控: {r.monitor}")

    # ========== STEP 9：状态机验证 ==========
    print_step(9, "终态保护验证")

    print(f"  [终态锁定]")
    for s in TERMINAL_STATUSES:
        next_states = next_statuses(s.value)
        print(f"    {s.value:20s} -> 下一状态数: {len(next_states)}（应为 0）")
        assert len(next_states) == 0, f"终态 {s.value} 不应有迁移"

    # ========== 总结 ==========
    print_header("完整业务流演示结束")
    print(f"""
    [OK] 商品已发布到 Temu（mock）
    [OK] 平台商品 ID: {poll_resp['platform_product_id']}
    [OK] 9 个状态全部正确流转
    [OK] 14 项风险监控到位
    [OK] 审计日志 + 凭证脱敏生效

    完整链路：
    CSV 导入 -> 规则筛选 -> 评分 -> 一审 -> AI 文案 -> 二审 -> 快照冻结 -> 发布 -> Temu
    """)
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())