"""V1.1-A2 类目字典同步测试"""
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.category_sync import (
    diff_dicts, generate_version_label, should_auto_activate
)


def test_diff_basic():
    print("[1/4] 基本 diff")
    old = [
        {"category_id": "PET-001", "name": "宠物玩具", "parent_id": "PET-ROOT"},
        {"category_id": "KIT-001", "name": "厨房餐具", "parent_id": "KIT-ROOT"},
    ]
    new = [
        {"category_id": "PET-001", "name": "宠物玩具（新）", "parent_id": "PET-ROOT"},  # 修改
        {"category_id": "KIT-001", "name": "厨房餐具", "parent_id": "KIT-ROOT"},  # 不变
        {"category_id": "PHN-001", "name": "手机壳", "parent_id": "PHN-ROOT"},  # 新增
    ]

    diff = diff_dicts(old, new)
    assert len(diff.added) == 1, f"应 1 个新增，实际 {len(diff.added)}"
    assert len(diff.modified) == 1, f"应 1 个修改，实际 {len(diff.modified)}"
    assert len(diff.removed) == 0
    print(f"  [OK] 新增: {len(diff.added)}, 修改: {len(diff.modified)}, 删除: {len(diff.removed)}")


def test_diff_removed():
    print("\n[2/4] 删除检测")
    old = [
        {"category_id": "OLD-001", "name": "已下架类目", "parent_id": "ROOT"},
        {"category_id": "KEEP-001", "name": "保留", "parent_id": "ROOT"},
    ]
    new = [
        {"category_id": "KEEP-001", "name": "保留", "parent_id": "ROOT"},
    ]
    diff = diff_dicts(old, new)
    assert diff.removed == ["OLD-001"]
    print(f"  [OK] 检测到下架类目: {diff.removed}")


def test_version_label():
    print("\n[3/4] 版本号生成")
    label = generate_version_label("us", datetime(2026, 9, 2, 13, 30, 0))
    assert label == "us-20260902133000"
    print(f"  [OK] us-20260902133000")


def test_auto_activate():
    print("\n[4/4] 自动激活阈值")
    # 小变更 → 自动激活
    small = diff_dicts([], [{"category_id": f"X-{i}"} for i in range(5)])
    assert should_auto_activate(small, threshold=10) is True
    print(f"  [OK] 5 项变更 → 自动激活")

    # 大变更 → 人工确认
    big = diff_dicts([], [{"category_id": f"X-{i}"} for i in range(20)])
    assert should_auto_activate(big, threshold=10) is False
    print(f"  [OK] 20 项变更 → 需人工确认")


def main():
    print("=" * 60)
    print("V1.1-A2 类目字典同步测试")
    print("=" * 60)
    test_diff_basic()
    test_diff_removed()
    test_version_label()
    test_auto_activate()
    print("\n" + "=" * 60)
    print("全部 V1.1-A2 测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()