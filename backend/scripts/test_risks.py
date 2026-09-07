"""W8-D6 14 风险点代码化测试 — PRD §20"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.risk_register import RISKS, RiskSeverity, get_risk, by_probability, all_codes


def test_14_risks():
    print("[1/4] 14 风险点齐备")
    assert len(RISKS) == 14, f"应 14 项风险，实际 {len(RISKS)}"
    print(f"  [OK] {len(RISKS)} 项风险全部覆盖")


def test_each_risk_has_mitigation():
    print("\n[2/4] 每项风险都有缓解措施")
    for r in RISKS:
        assert r.code.startswith("R-")
        assert r.risk
        assert r.probability in (RiskSeverity.LOW, RiskSeverity.MEDIUM, RiskSeverity.HIGH, RiskSeverity.VERY_HIGH)
        assert r.impact
        assert r.mitigation
        assert r.monitor  # 每项必须有监控指标
    print(f"  [OK] 14 项风险 schema 完整（含概率/影响/缓解/监控）")


def test_high_risks():
    print("\n[3/4] 高风险项 ≥ 5")
    high = by_probability(RiskSeverity.HIGH) + by_probability(RiskSeverity.VERY_HIGH)
    assert len(high) >= 5, f"应 ≥5 项高风险，实际 {len(high)}"
    print(f"  [OK] 高风险 {len(high)} 项：")
    for r in high:
        print(f"    {r.code}: {r.risk}")


def test_specific_mitigations():
    print("\n[4/4] 典型风险对应缓解已实现")

    # R-09 API 超时 → 幂等键 + 查询核实
    r = get_risk("R-09")
    assert "幂等" in r.mitigation or "查询" in r.mitigation
    print(f"  [OK] R-09（API 超时）→ {r.mitigation[:50]}...")

    # R-05 AI 幻觉 → 事实白名单
    r = get_risk("R-05")
    assert "白名单" in r.mitigation or "事实" in r.mitigation
    print(f"  [OK] R-05（AI 幻觉）→ {r.mitigation[:50]}...")

    # R-14 凭据泄露 → 加密 + 脱敏
    r = get_risk("R-14")
    assert "加密" in r.mitigation or "脱敏" in r.mitigation
    print(f"  [OK] R-14（凭据泄露）→ {r.mitigation[:50]}...")


def main():
    print("=" * 60)
    print("W8-D6 14 风险点代码化测试 — PRD §20")
    print("=" * 60)
    test_14_risks()
    test_each_risk_has_mitigation()
    test_high_risks()
    test_specific_mitigations()
    print("\n" + "=" * 60)
    print("全部风险点测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()