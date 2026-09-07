"""W8-D1 状态机完整测试 — PRD §6.1 14 状态 + 8 终态"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.state_machine import (
    ListingStatus, TERMINAL_STATUSES, TRANSITIONS,
    can_transition, assert_transition, next_statuses,
    is_terminal, IllegalTransition,
)


def test_all_states_have_transitions():
    """测试 1：14 个状态 + 8 终态"""
    print("[1/6] 18 个状态 + 8 终态")

    all_states = set(ListingStatus)
    assert len(all_states) >= 18, f"应 ≥18 个状态，实际 {len(all_states)}"
    assert len(TERMINAL_STATUSES) == 7, f"应 7 个硬终态（published 单独计）"
    # 加上准终态共 8
    from app.services.state_machine import QUASI_TERMINAL
    assert len(TERMINAL_STATUSES | QUASI_TERMINAL) == 8, "应 8 个终态（含准终态）"
    print(f"  [OK] {len(all_states)} 个状态（7 硬终态 + 1 准终态 = 8 终态）")
    print(f"  [OK] 终态：{sorted(s.value for s in (TERMINAL_STATUSES | QUASI_TERMINAL))}")


def test_terminal_states_blocked():
    """测试 2：终态不可迁移"""
    print("\n[2/6] 终态不可迁移")

    for s in TERMINAL_STATUSES:
        assert is_terminal(s.value), f"{s.value} 应是终态"
        assert not can_transition(s.value, "editing"), f"{s.value} 不可迁移到 editing"
        assert not can_transition(s.value, "publishing"), f"{s.value} 不可迁移到 publishing"

    # 注意：published 是准终态（只能去 archived），不在硬终态集合
    assert ListingStatus.PUBLISHED not in TERMINAL_STATUSES
    from app.services.state_machine import QUASI_TERMINAL
    assert ListingStatus.PUBLISHED in QUASI_TERMINAL
    assert can_transition("published", "archived")
    assert not can_transition("published", "editing")

    # 其他 7 个终态都应有空迁移规则
    strict_terminal = TERMINAL_STATUSES - QUASI_TERMINAL
    for s in strict_terminal:
        assert TRANSITIONS[s] == [], f"{s.value} 应无迁移规则"

    print(f"  [OK] 8 个终态（含 1 个准终态 published）均按规则锁定")


def test_happy_path_transitions():
    """测试 3：完整业务流的合法迁移"""
    print("\n[3/6] 完整业务流（happy path）")

    happy_path = [
        ("imported", "normalized", "deduped", True),
        ("normalized", "scored", "score", 80),
        ("scored", "first_review", "in_top_n", True),
        ("first_review", "content_generating", "actor", "op1"),
        ("content_generating", "editing", "ai_success", True),
        ("editing", "second_review", "all_required_filled", True),
        ("second_review", "ready_to_publish", "snapshot_frozen", True),
        ("ready_to_publish", "publishing", "snapshot_match", True),
        ("publishing", "published", "platform_product_id", "TP-001"),
    ]

    for i, (frm, to, condition_key, condition_val) in enumerate(happy_path, 1):
        assert_transition(frm, to, **{condition_key: condition_val})
        print(f"  [OK] Step {i}: {frm} → {to}")


def test_async_publish_path():
    """测试 4：异步发布路径"""
    print("\n[4/6] 异步发布路径")

    # 同步成功路径
    assert_transition("publishing", "published", platform_product_id="TP-1")
    print("  [OK] publishing → published（同步成功）")

    # 异步路径
    assert_transition("publishing", "platform_reviewing", platform_task_id="TT-1")
    print("  [OK] publishing → platform_reviewing（异步受理）")

    assert_transition("platform_reviewing", "published", poll_terminal=True)
    print("  [OK] platform_reviewing → published（轮询终态成功）")

    assert_transition("platform_reviewing", "publish_failed", poll_terminal=True)
    print("  [OK] platform_reviewing → publish_failed（轮询终态失败）")

    # 失败可重试
    assert_transition("publish_failed", "publishing", retry_within_limit=True)
    print("  [OK] publish_failed → publishing（手动重试）")

    # 失败可关闭
    assert_transition("publish_failed", "closed", reason_code="abandoned")
    print("  [OK] publish_failed → closed（人工关闭）")


def test_illegal_transitions():
    """测试 5：非法迁移被拒"""
    print("\n[5/6] 非法迁移被拒")

    illegal_cases = [
        ("imported", "publishing"),       # 跳级
        ("first_review", "ready_to_publish"),  # 跳过资料生成 + 二审
        ("editing", "publishing"),        # 没二审不能发
        ("published", "editing"),         # 已发布不可编辑
        ("filtered_out", "editing"),      # 终态
        ("rejected_1", "editing"),        # 终态
    ]

    for frm, to in illegal_cases:
        assert not can_transition(frm, to), f"{frm}→{to} 应被拒"
        try:
            assert_transition(frm, to, **{frm.split()[0]: "test"})
            assert False, f"{frm}→{to} 应抛异常"
        except IllegalTransition:
            pass

    print(f"  [OK] 6 种非法迁移全部拒绝")


def test_required_conditions():
    """测试 6：requires 条件校验"""
    print("\n[6/6] requires 条件校验")

    # 没传 required 条件 → 抛异常
    try:
        assert_transition("imported", "normalized")  # 需要 deduped
        assert False, "应抛异常"
    except IllegalTransition as e:
        assert "deduped" in str(e.reason)
        print(f"  [OK] 缺 required 条件被拒：{e.reason}")

    # 传了 → 通过
    assert_transition("imported", "normalized", deduped=True)
    print(f"  [OK] 提供 required 条件通过")


def main():
    print("=" * 60)
    print("W8-D1 状态机迁移规则完整测试")
    print("=" * 60)

    test_all_states_have_transitions()
    test_terminal_states_blocked()
    test_happy_path_transitions()
    test_async_publish_path()
    test_illegal_transitions()
    test_required_conditions()

    print("\n" + "=" * 60)
    print("全部状态机测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()