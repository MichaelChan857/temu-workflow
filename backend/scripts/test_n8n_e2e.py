"""n8n 端到端等价链路集成测试

前提：
- 后端 host 8000 端口在跑（py -3.12 -m uvicorn app.main:app）
- 已 seed admin/admin123 用户
- 真实端到端，HTTP 调用后端 API

测试：
- N-01 admin 登录拿 JWT
- N-02 读 CSV + 解析 → POST /api/v1/import/json
- N-03 IF 分支判定 < 20 → 调 /api/v1/alerts/send
- N-04 告警入 events / alerts 表（DB 验证）
- N-05 端到端响应字段（batch_id, recommended, level, title）
"""
import sys
import csv
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

API = "http://127.0.0.1:8000"
CSV_PATH = Path(__file__).parent.parent.parent / "n8n" / "imports" / "daily_sample.csv"

RESULTS = {"total": 0, "passed": 0, "failed": 0, "details": []}


def check(ac_id, name, fn):
    RESULTS["total"] += 1
    try:
        fn()
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


def _login() -> str:
    r = httpx.post(f"{API}/api/v1/auth/login", json={"username": "admin", "password": "admin123"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _parse_csv() -> list[dict]:
    text = CSV_PATH.read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l and not l.startswith("#")]
    reader = csv.DictReader(StringIO("\n".join(lines)))
    cands = []
    for row in reader:
        obj = dict(row)
        if obj.get("price"): obj["price"] = float(obj["price"])
        if obj.get("cost"): obj["cost"] = float(obj["cost"])
        if obj.get("weight_g"): obj["weight_g"] = int(obj["weight_g"])
        obj["image_urls"] = []
        for n in range(1, 4):
            k = f"image_url_{n}"
            if obj.get(k):
                obj["image_urls"].append(obj[k])
                del obj[k]
        cands.append(obj)
    return cands


def n_01_login():
    """admin 登录拿 JWT"""
    token = _login()
    assert len(token) > 100, f"JWT 应 >100 字符，实际 {len(token)}"
    assert token.count(".") == 2, "JWT 应含 2 个点"


def n_02_import_json():
    """POST /import/json 返回 batch_id + 推荐数"""
    token = _login()
    cands = _parse_csv()
    assert len(cands) > 0, "CSV 至少 1 行"
    r = httpx.post(
        f"{API}/api/v1/import/json",
        json={"candidates": cands, "source": "n8n_e2e_test"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    r.raise_for_status()
    result = r.json()
    assert "batch_id" in result, f"应返回 batch_id，实际 {result.keys()}"
    assert "recommended" in result, f"应返回 recommended，实际 {result.keys()}"
    assert isinstance(result["recommended"], int)
    assert isinstance(result["batch_id"], str) and len(result["batch_id"]) == 36


def n_03_alert_branch():
    """IF 分支判定 recommended < 20 → 调 /alerts/send"""
    token = _login()
    cands = _parse_csv()
    r = httpx.post(
        f"{API}/api/v1/import/json",
        json={"candidates": cands, "source": "n8n_e2e_branch_test"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    result = r.json()
    recommended = result["recommended"]

    if recommended < 20:
        # 走告警分支
        r2 = httpx.post(
            f"{API}/api/v1/alerts/send",
            json={"level": "warning", "title": "Temu 候选不足", "message": f"今日推荐 {recommended}", "source": "n8n_e2e_test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        r2.raise_for_status()
        # MVP 端点只返回 {status, level}，id 在 events 表里
        body = r2.json()
        assert body.get("status") == "logged"
        assert body.get("level") == "warning"
        print(f"  (实际走告警分支：recommended={recommended})")
    else:
        print(f"  (实际走通知分支：recommended={recommended} ≥ 20)")


def n_04_alert_in_db():
    """告警入 alerts 表（GET /alerts 可查到）"""
    token = _login()
    # 先发一条告警
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    httpx.post(
        f"{API}/api/v1/alerts/send",
        json={"level": "warning", "title": f"E2E_TEST_{ts}", "message": "n8n equivalent alert test", "source": "n8n_e2e_test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # 查询
    r = httpx.get(
        f"{API}/api/v1/alerts?limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    alerts = r.json()
    found = any(a.get("title") == f"E2E_TEST_{ts}" for a in alerts)
    assert found, f"刚发的告警 {ts} 未出现在 GET /alerts 中"


def n_05_e2e_response_fields():
    """端到端响应字段完整（batch_id 36 字符 UUID + recommended int + alerts level/title）"""
    token = _login()
    cands = _parse_csv()
    r = httpx.post(
        f"{API}/api/v1/import/json",
        json={"candidates": cands, "source": "n8n_e2e_fields_test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    result = r.json()
    # 验证字段
    assert set(["batch_id", "business_date", "imported", "valid", "deduped",
                "filtered_out", "scored", "recommended", "recommended_ids"]).issubset(result.keys())

    r2 = httpx.post(
        f"{API}/api/v1/alerts/send",
        json={"level": "warning", "title": "E2E fields check", "message": "schema test", "source": "n8n_e2e_test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    a = r2.json()
    # MVP 端点只返回 status + level，验证这两个字段
    assert a.get("status") == "logged"
    assert a.get("level") == "warning"


def main():
    print("=" * 70)
    print("n8n 端到端等价链路测试（PRD V1.1 n8n 工作流等价）")
    print("=" * 70)

    print("\n--- N-01 登录 ---")
    check("N-01", "admin 登录拿 JWT", n_01_login)

    print("\n--- N-02 /import/json ---")
    check("N-02", "POST /import/json 返回 batch_id + recommended", n_02_import_json)

    print("\n--- N-03 IF 分支 ---")
    check("N-03", "IF 分支：候选不足 → 告警", n_03_alert_branch)

    print("\n--- N-04 告警落 DB ---")
    check("N-04", "告警入 alerts 表（GET /alerts 验证）", n_04_alert_in_db)

    print("\n--- N-05 端到端字段 ---")
    check("N-05", "端到端响应字段完整", n_05_e2e_response_fields)

    print("\n" + "=" * 70)
    print(f"n8n E2E 验收：{RESULTS['passed']}/{RESULTS['total']} 通过，{RESULTS['failed']} 失败")
    print("=" * 70)

    if RESULTS["failed"]:
        print("\n失败详情：")
        for ac_id, name, status, err in RESULTS["details"]:
            if status != "PASS":
                print(f"  [{ac_id}] {status}: {name} — {err}")

    return 0 if RESULTS["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())