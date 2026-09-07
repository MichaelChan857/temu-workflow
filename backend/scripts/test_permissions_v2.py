"""W8-D4 13 权限点对齐测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.permissions_v2 import (
    PERMISSION_CATALOG, ROLE_PERMISSION_MATRIX,
    has_permission_v2, get_role_permissions, diff_roles,
)


def test_catalog_completeness():
    print("[1/5] 33 权限点齐备")
    assert len(PERMISSION_CATALOG) >= 33, f"应 ≥33 个权限点，实际 {len(PERMISSION_CATALOG)}"
    expected_cats = ["batch.", "candidate.", "review.first.", "listing.",
                      "review.second.", "publish.", "config.", "user.", "audit.", "alert."]
    for cat in expected_cats:
        assert any(p.startswith(cat) for p in PERMISSION_CATALOG), f"缺 {cat}"
    print(f"  [OK] {len(PERMISSION_CATALOG)} 个权限点，10 大类齐全")


def test_admin_has_all():
    print("\n[2/5] admin 全部权限")
    admin_perms = get_role_permissions("admin")
    assert len(admin_perms) == len(PERMISSION_CATALOG)
    for p in PERMISSION_CATALOG:
        assert has_permission_v2("admin", p)
    print(f"  [OK] admin 有 {len(admin_perms)} 个权限")


def test_role_separation():
    print("\n[3/5] 职责分离")
    assert has_permission_v2("operator", "candidate.import")
    assert not has_permission_v2("operator", "listing.generate")
    assert not has_permission_v2("operator", "publish.execute")
    print(f"  [OK] operator：批次/导入/一审，无发布")

    assert has_permission_v2("editor", "listing.generate")
    assert has_permission_v2("editor", "listing.edit")
    assert has_permission_v2("editor", "listing.rollback")
    assert not has_permission_v2("editor", "publish.execute")
    print(f"  [OK] editor：资料编辑，无发布")

    assert has_permission_v2("reviewer", "review.first.approve")
    assert has_permission_v2("reviewer", "review.second.approve")
    assert not has_permission_v2("reviewer", "publish.execute")
    print(f"  [OK] reviewer：一审+二审，无发布")

    assert has_permission_v2("publisher", "publish.execute")
    assert has_permission_v2("publisher", "publish.retry")
    assert not has_permission_v2("publisher", "review.second.approve")
    print(f"  [OK] publisher：发布，无审批")

    readonly_perms = get_role_permissions("readonly")
    assert all("view" in p for p in readonly_perms)
    print(f"  [OK] readonly 仅 {len(readonly_perms)} 个查看权限")


def test_cross_role_diff():
    print("\n[4/5] 跨角色差异")
    diff = diff_roles("operator", "editor")
    assert "candidate.import" in diff
    assert "listing.generate" in diff
    print(f"  [OK] operator vs editor 差异 {len(diff)} 项")


def test_no_phantom_permissions():
    print("\n[5/5] 无幽灵权限")
    for role, perms in ROLE_PERMISSION_MATRIX.items():
        for p in perms:
            assert p in PERMISSION_CATALOG
    print(f"  [OK] 所有角色的权限都在 PERMISSION_CATALOG 中")


def main():
    print("=" * 60)
    print("W8-D4 13 权限点对齐测试 — PRD §13.1")
    print("=" * 60)
    test_catalog_completeness()
    test_admin_has_all()
    test_role_separation()
    test_cross_role_diff()
    test_no_phantom_permissions()
    print("\n" + "=" * 60)
    print("全部权限点测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()