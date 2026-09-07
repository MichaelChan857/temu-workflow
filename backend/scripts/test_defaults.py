"""W8-D7 §21 待确认默认值测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.defaults import DEFAULTS, get_all_defaults, get_decision, unresolved, resolved_with_default


def test_13_defaults():
    print("[1/4] 13 项默认值齐备")
    assert len(DEFAULTS) == 13, f"应 13 项，实际 {len(DEFAULTS)}"
    print(f"  [OK] 13 项默认值齐备")


def test_each_has_value():
    print("\n[2/4] 每项都有默认值")
    for d in DEFAULTS:
        assert d.code.startswith("D-")
        assert d.question
        assert d.default_value
        assert d.rationale
        assert d.configurable_via
    print(f"  [OK] 13 项 schema 完整")


def test_resolved_count():
    print("\n[3/4] 已提供默认值 vs 未提供")
    resolved = resolved_with_default()
    unres = unresolved()
    print(f"  已提供默认值：{len(resolved)} 项")
    print(f"  待客户填写：{len(unres)} 项")
    assert len(resolved) >= 10, "应 ≥10 项提供默认值"
    assert len(resolved) + len(unres) == 13


def test_specific_defaults():
    print("\n[4/4] 典型默认值")
    # D-03 任务时间
    d = get_decision("D-03")
    assert "06:00" in d.default_value or "20" in d.default_value
    print(f"  [OK] D-03 默认任务时间：{d.default_value}")

    # D-05 评分权重
    d = get_decision("D-05")
    assert "25" in d.default_value and "75" in d.default_value
    print(f"  [OK] D-05 默认评分：{d.default_value[:40]}...")

    # D-06 同人校验
    d = get_decision("D-06")
    assert "建议" in d.default_value or "suggested" in d.default_value
    print(f"  [OK] D-06 默认同人策略：{d.default_value}")


def main():
    print("=" * 60)
    print("W8-D7 §21 待确认默认值测试")
    print("=" * 60)
    test_13_defaults()
    test_each_has_value()
    test_resolved_count()
    test_specific_defaults()
    print("\n" + "=" * 60)
    print("全部默认值测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()