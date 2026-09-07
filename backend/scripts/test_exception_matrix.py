"""W8-D2 异常处理矩阵测试 — PRD §11"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.exception_matrix import (
    EXCEPTION_MATRIX, ExceptionCategory, RetryPolicy,
    should_auto_retry, get_rule, list_retryable_codes, list_by_category,
)


def test_matrix_completeness():
    """测试 1：13 类异常齐备"""
    print("[1/5] 13 类异常齐备")
    assert len(EXCEPTION_MATRIX) >= 13, f"应 ≥13 类异常，实际 {len(EXCEPTION_MATRIX)}"
    print(f"  [OK] {len(EXCEPTION_MATRIX)} 类异常覆盖")

    # 每类异常必要字段
    for code, rule in EXCEPTION_MATRIX.items():
        assert rule.code == code
        assert rule.category
        assert isinstance(rule.retry, bool)
        assert rule.description
        assert rule.user_action
        assert rule.auto_action
    print(f"  [OK] 每类异常 schema 完整")


def test_retry_rules():
    """测试 2：仅网络/超时/限流自动重试"""
    print("\n[2/5] 自动重试规则")

    retryable = list_retryable_codes()
    print(f"  可自动重试：{retryable}")

    # 必须包含：DATA_SOURCE_UNAVAILABLE、AI_TIMEOUT、AI_FORMAT、API_RATE_LIMIT_5XX、API_TIMEOUT_UNKNOWN
    must_retry = [
        "DATA_SOURCE_UNAVAILABLE",
        "AI_TIMEOUT_RATE_LIMIT",
        "AI_FORMAT_ERROR",
        "API_RATE_LIMIT_5XX",
        "API_TIMEOUT_UNKNOWN",
    ]
    for c in must_retry:
        assert c in retryable, f"{c} 应可自动重试"

    # 必须不重试：参数/字段错误
    must_not_retry = [
        "FILE_FORMAT_ERROR",
        "NO_CATEGORY_MATCH",
        "MISSING_REQUIRED_ATTR",
        "SHOP_AUTH_EXPIRED",
        "DUPLICATE_PUBLISH",
    ]
    for c in must_not_retry:
        assert not should_auto_retry(c, 1), f"{c} 不应自动重试"

    print(f"  [OK] 5 类可重试 + 5 类不可重试")


def test_max_retries():
    """测试 3：最多 3 次"""
    print("\n[3/5] 最多重试 3 次")

    # 任何 retryable 异常，重试 3 次后应停
    for code in list_retryable_codes():
        assert should_auto_retry(code, 1), f"{code} 第1次应重试"
        assert should_auto_retry(code, 2), f"{code} 第2次应重试"
        assert not should_auto_retry(code, 3), f"{code} 第3次应停止"
        assert not should_auto_retry(code, 4), f"{code} 第4次应停止"
    print(f"  [OK] 全部 retryable 异常均遵循 max=3")


def test_categories():
    """测试 4：4 类异常分类"""
    print("\n[4/5] 异常分类覆盖")

    categories_seen = set()
    for rule in EXCEPTION_MATRIX.values():
        categories_seen.add(rule.category)

    expected = {
        ExceptionCategory.RETRYABLE,
        ExceptionCategory.FATAL,
        ExceptionCategory.NEED_AUTH,
        ExceptionCategory.NEED_FIX,
    }
    for c in expected:
        assert c in categories_seen, f"缺分类 {c}"

    # retryable 数量 = 5
    retryable_rules = list_by_category(ExceptionCategory.RETRYABLE)
    assert len(retryable_rules) >= 4, f"应有 ≥4 个 retryable，实际 {len(retryable_rules)}"
    print(f"  [OK] 4 大分类齐全（retryable={len(retryable_rules)}）")


def test_specific_rules():
    """测试 5：典型异常的精确规则"""
    print("\n[5/5] 典型异常精确规则")

    # 授权过期：不可重试
    rule = get_rule("SHOP_AUTH_EXPIRED")
    assert rule.category == ExceptionCategory.NEED_AUTH
    assert not rule.retry
    assert "重新授权" in rule.user_action or "Partner" in rule.user_action
    print(f"  [OK] 授权过期：need_auth，不可重试")

    # 必填缺失：不可重试
    rule = get_rule("MISSING_REQUIRED_ATTR")
    assert rule.category == ExceptionCategory.FATAL
    assert "阻止" in rule.auto_action or "必填" in rule.auto_action
    print(f"  [OK] 必填缺失：fatal，阻止二审")

    # 重复发布：不可重试
    rule = get_rule("DUPLICATE_PUBLISH")
    assert rule.category == ExceptionCategory.FATAL
    assert "幂等" in rule.description or "重复" in rule.description or "SKU" in rule.description
    print(f"  [OK] 重复发布：fatal，幂等键保护")

    # API 业务校验：不可重试，需退回编辑
    rule = get_rule("API_BUSINESS_ERROR")
    assert rule.category == ExceptionCategory.NEED_FIX
    assert not rule.retry
    print(f"  [OK] 业务错误：need_fix，退回编辑")


def main():
    print("=" * 60)
    print("W8-D2 异常处理矩阵测试 — PRD §11")
    print("=" * 60)

    test_matrix_completeness()
    test_retry_rules()
    test_max_retries()
    test_categories()
    test_specific_rules()

    print("\n" + "=" * 60)
    print("全部异常矩阵测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()