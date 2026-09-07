"""W8-D8 集成测试套件 — 一次性跑完所有 W8 子测试"""
import subprocess
import sys
from pathlib import Path

SCRIPTS = [
    "test_state_machine.py",
    "test_exception_matrix.py",
    "test_audit.py",
    "test_permissions_v2.py",
    "test_nonfunctional.py",
    "test_risks.py",
    "test_defaults.py",
    # 已有的
    "test_workflow_e2e.py",
    "test_claude_e2e.py",
    "test_publish_e2e.py",
    "test_xlsx_e2e.py",
    "test_security.py",
    "test_acceptance.py",  # 15 条 AC
    # V2.0
    "test_v20_feedback.py",      # 5 断言
    "test_v20_calibration.py",   # 7 断言
    "test_v20_dedup.py",         # 5 断言
    # n8n 等价端到端（需后端 8000 端口在跑）
    "test_n8n_e2e.py",           # 5 断言
    # 生产部署准备（V1.x + V2.0 部署代码验证，无需后端）
    "test_deploy_prep.py",       # 3 断言
]


def main():
    base = Path(__file__).parent
    results = []
    total = 0
    passed = 0
    failed = 0

    print("=" * 70)
    print("W8 集成测试套件 — 全部子测试")
    print("=" * 70)
    print()

    for script in SCRIPTS:
        path = base / script
        if not path.exists():
            print(f"[SKIP] {script}（不存在）")
            continue
        total += 1
        print(f"\n>>> Running {script}")
        print("-" * 70)
        # test_n8n_e2e.py 需要后端 host 8000 可达；不可达则 skip（不算失败）
        skip_if_unreachable = (script == "test_n8n_e2e.py")
        result = subprocess.run(
            ["py", "-3.12", "-X", "utf8", str(path)],
            capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace",
        )
        if skip_if_unreachable and result.returncode != 0 and (
            "Connection refused" in result.stderr
            or "ConnectionRefused" in result.stderr
            or "httpx.ConnectError" in result.stderr
            or "Connection refused" in result.stdout
            or "ConnectError" in result.stdout
            or "无法连接" in result.stdout
        ):
            print(f"[SKIP] {script}（后端 8000 端口不可达，跳过）")
            total -= 1  # 不计 total
            continue
        if result.returncode == 0:
            passed += 1
            # 提取最后一行作为摘要
            last_lines = result.stdout.strip().split("\n")[-5:]
            summary = next((l for l in last_lines if "通过" in l or "all" in l.lower()), "")
            print(f"[PASS] {script}")
            if summary:
                print(f"       {summary.strip()}")
        else:
            failed += 1
            print(f"[FAIL] {script}")
            # 打印最后 10 行错误
            print("--- stdout tail ---")
            print("\n".join(result.stdout.split("\n")[-10:]))
            print("--- stderr tail ---")
            print("\n".join(result.stderr.split("\n")[-10:]))

    print("\n" + "=" * 70)
    print(f"集成测试结果：{passed}/{total} 通过，{failed} 失败")
    print("=" * 70)

    if failed == 0:
        print("\n[OK] 所有 W8 测试通过")
        return 0
    else:
        print(f"\n[FAIL] {failed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())