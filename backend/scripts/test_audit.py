"""W8-D3 日志审计测试 — PRD §12"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.audit import (
    LogType, RETENTION_DAYS, scrub, scrub_dict,
    field_audit, make_log, check_retention, should_prune,
)


def test_seven_log_types():
    """测试 1：7 类日志齐全 + 留存期正确"""
    print("[1/5] 7 类日志 + 留存期")
    assert len(LogType) == 7, f"应 7 类日志，实际 {len(LogType)}"
    print(f"  [OK] 7 类：{[l.value for l in LogType]}")

    # 留存期校验
    assert RETENTION_DAYS[LogType.BUSINESS] >= 730  # ≥2 年
    assert RETENTION_DAYS[LogType.AUDIT] >= 730
    assert RETENTION_DAYS[LogType.API] >= 180
    assert RETENTION_DAYS[LogType.AI] >= 180
    assert RETENTION_DAYS[LogType.SYSTEM] >= 90
    print(f"  [OK] 留存期符合 PRD §12.1")


def test_no_secrets_leaked():
    """测试 2：凭证脱敏"""
    print("\n[2/5] 凭证脱敏")

    test_cases = [
        ("password=admin123", "admin123"),
        ("API_KEY=sk-1234567890abcdefghij", "sk-1234567890"),
        ("Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", "eyJhbGciOiJIUzI1NiJ9"),
        ("token=abc123secret", "abc123secret"),
        ("手机 13800138000", "13800138000"),
        ("身份证 110101199001011234", "110101199001011234"),
        ("邮箱 user@example.com", "user@example.com"),
    ]

    for original, must_be_scrubbed in test_cases:
        result = scrub(original)
        assert must_be_scrubbed not in result, f"未脱敏：{original} → {result}"
        assert "[REDACTED" in result or result == original, f"应被脱敏或保留：{original} → {result}"

    print(f"  [OK] 7 种敏感信息全部脱敏")


def test_dict_recursive():
    """测试 3：递归脱敏 dict / list"""
    print("\n[3/5] 递归脱敏 dict / list")
    payload = {
        "user": "alice",
        "credentials": {"password": "secret123", "api_key": "sk-xxx"},
        "tokens": ["token1", "token2"],
        "metadata": {"contact": "13800138000"},
    }
    out = scrub_dict(payload)
    assert "secret123" not in str(out)
    assert "sk-xxx" not in str(out)
    assert "13800138000" not in str(out)
    assert out["user"] == "alice"  # 正常字段保留
    assert out["credentials"]["password"] == "[REDACTED]"
    assert all("[REDACTED" in t for t in out["tokens"])
    print(f"  [OK] 嵌套结构全部脱敏")


def test_field_audit():
    """测试 4：字段级 before/after"""
    print("\n[4/5] 字段级变更审计")

    before = {"title": "Original", "price": 19.99, "supplier_sku": "SKU-001"}
    after = {"title": "Modified", "price": 24.99, "supplier_sku": "SKU-001"}

    audit = field_audit(before, after)
    assert "title" in audit["changed_fields"]
    assert "price" in audit["changed_fields"]
    assert "supplier_sku" not in audit["changed_fields"]
    print(f"  [OK] 变更字段：{audit['changed_fields']}")


def test_make_log_and_retention():
    """测试 5：make_log + 留存期清理"""
    print("\n[5/5] 构造日志 + 留存期检查")

    log = make_log(
        log_type=LogType.AUDIT,
        entity_type="candidate",
        entity_id="c-123",
        event_type="first_review_approve",
        actor_id="u-1",
        actor_name="alice",
        reason="approve",
        payload={"from_status": "first_review", "to_status": "content_generating"},
    )
    assert log["log_type"] == "audit"
    assert log["retention_days"] == 730
    assert log["actor_name"] == "alice"
    print(f"  [OK] 日志字段完整")

    # 留存期检查
    assert check_retention(LogType.BUSINESS, 700) is True, "2 年内"
    assert check_retention(LogType.BUSINESS, 731) is False, "超过 2 年"
    assert should_prune(LogType.SYSTEM, 90) is True, "90 天清理"
    assert should_prune(LogType.SYSTEM, 89) is False
    print(f"  [OK] 留存期检查正确")


def main():
    print("=" * 60)
    print("W8-D3 日志审计测试 — PRD §12")
    print("=" * 60)

    test_seven_log_types()
    test_no_secrets_leaked()
    test_dict_recursive()
    test_field_audit()
    test_make_log_and_retention()

    print("\n" + "=" * 60)
    print("全部日志审计测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()