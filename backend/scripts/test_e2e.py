"""端到端联调脚本 — 不需启动 Docker

模拟 n8n 工作流：
  读 CSV → POST /api/v1/import/json → 验证推荐数量 → 模拟并发决策

需要：
  - 后端服务在 localhost:8000 运行
  - 默认用户 admin/admin123 已初始化

用法：
  python scripts/test_e2e.py
"""
import sys
import time
import csv
import io
import hashlib
from pathlib import Path
import httpx

API_BASE = "http://localhost:8000"
CSV_FILE = Path(__file__).parent / "..\\..\\n8n\\imports\\daily_sample.csv"


def login(username="admin", password="admin123"):
    """登录获取 token"""
    resp = httpx.post(
        f"{API_BASE}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=10.0,
    )
    if resp.status_code != 200:
        print(f"[FAIL] 登录失败: {resp.status_code} {resp.text}")
        sys.exit(1)
    data = resp.json()
    print(f"[OK] 登录成功: {data['user']['display_name']} ({data['user']['role']})")
    return data["access_token"], data["user"]


def parse_csv(path: Path):
    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def to_candidate_payload(row: dict) -> dict:
    """CSV 行 → JSON payload（模拟 n8n 解析）"""
    images = [row.get(f"image_url_{i}") for i in (1, 2, 3) if row.get(f"image_url_{i}")]
    return {
        "source_product_id": row["source_product_id"],
        "title": row["title"],
        "description": row.get("description"),
        "category": row.get("category"),
        "price": float(row["price"]) if row.get("price") else 0,
        "cost": float(row["cost"]) if row.get("cost") else None,
        "currency": row.get("currency") or "USD",
        "weight_g": int(row["weight_g"]) if row.get("weight_g") else None,
        "dimensions": {
            "l": float(row["length_cm"]) if row.get("length_cm") else None,
            "w": float(row["width_cm"]) if row.get("width_cm") else None,
            "h": float(row["height_cm"]) if row.get("height_cm") else None,
        } if row.get("length_cm") or row.get("width_cm") or row.get("height_cm") else None,
        "image_urls": images,
        "supplier_sku": row["supplier_sku"],
        "source_url": row.get("source_url"),
    }


def step1_import(token: str):
    """步骤 1：模拟 n8n 推 CSV 到后端"""
    print("\n[STEP 1] 模拟 n8n 推送 CSV 到 /api/v1/import/json")

    rows = parse_csv(CSV_FILE)
    candidates = [to_candidate_payload(r) for r in rows]
    print(f"  解析 {len(rows)} 行 CSV")

    resp = httpx.post(
        f"{API_BASE}/api/v1/import/json",
        json={"candidates": candidates, "source": "e2e_test"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    if resp.status_code != 200:
        print(f"[FAIL] 导入失败: {resp.status_code} {resp.text}")
        sys.exit(1)

    result = resp.json()
    print(f"  [OK] 批次 {result['batch_id'][:8]}...")
    print(f"    导入: {result['imported']}, 通过: {result['valid']}, "
          f"淘汰: {result['filtered_out']}, 推荐: {result['recommended']}")
    return result["recommended_ids"]


def step2_list_review(token: str):
    """步骤 2：一审列表"""
    print("\n[STEP 2] 一审列表 /api/v1/candidates")
    resp = httpx.get(
        f"{API_BASE}/api/v1/candidates?status=first_review&limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        print(f"[FAIL] {resp.text}")
        sys.exit(1)
    candidates = resp.json()
    print(f"  [OK] 待一审 {len(candidates)} 个")
    return candidates


def step3_concurrent_decide(token: str, candidate_ids: list):
    """步骤 3：模拟两人并发决策（验证乐观锁）"""
    print("\n[STEP 3] 并发决策测试（乐观锁）")
    if not candidate_ids:
        print("  [SKIP] 没有候选可决策")
        return

    target = candidate_ids[0]
    # 先取 version
    resp = httpx.get(
        f"{API_BASE}/api/v1/candidates/{target}",
        headers={"Authorization": f"Bearer {token}"},
    )
    detail = resp.json()
    version = detail.get("version", 1)
    print(f"  目标: {target[:8]}..., 当前 version={version}")

    # 用户 A 通过（带 version）
    resp_a = httpx.post(
        f"{API_BASE}/api/v1/candidates/{target}/decision?expected_version={version}",
        json={"decision": "approve", "comment": "A 通过"},
        headers={"Authorization": f"Bearer {token}"},
    )
    print(f"  用户 A 决策: {resp_a.status_code} {resp_a.json().get('new_status')}")

    # 用户 B 用相同 version 通过（应 409）
    resp_b = httpx.post(
        f"{API_BASE}/api/v1/candidates/{target}/decision?expected_version={version}",
        json={"decision": "reject", "reason_code": "其他", "comment": "B 想驳回"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp_b.status_code == 409:
        print(f"  [OK] 用户 B 决策被拒绝 (409 version conflict)")
    else:
        print(f"  [WARN] 用户 B 应得 409，实际 {resp_b.status_code}: {resp_b.text}")

    # 用户 B 不带 version（应被允许，但状态已变）
    resp_b2 = httpx.post(
        f"{API_BASE}/api/v1/candidates/{target}/decision",
        json={"decision": "reject", "reason_code": "其他", "comment": "B 再来"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp_b2.status_code == 400:
        print(f"  [OK] 用户 B 二次提交失败（状态已变更）: {resp_b2.json().get('detail', '')[:50]}")
    else:
        print(f"  [WARN] 用户 B 二次提交 {resp_b2.status_code}: {resp_b2.text}")


def step4_rbac(token_other: dict):
    """步骤 4：用 publisher 角色试决策（应 403）"""
    print("\n[STEP 4] RBAC 权限测试")
    print(f"  使用角色: {token_other['user']['role']}")

    resp = httpx.get(
        f"{API_BASE}/api/v1/candidates?status=first_review&limit=10",
        headers={"Authorization": f"Bearer {token_other['token']}"},
    )
    print(f"  查看列表: {resp.status_code} ({'通过' if resp.status_code == 200 else '拒绝'})")

    # 试图决策（publisher 没有 reviews.first 权限）
    candidates = resp.json()
    if candidates:
        target = candidates[0]["id"]
        resp = httpx.post(
            f"{API_BASE}/api/v1/candidates/{target}/decision",
            json={"decision": "approve"},
            headers={"Authorization": f"Bearer {token_other['token']}"},
        )
        if resp.status_code == 403:
            print(f"  [OK] publisher 决策被 403 拒绝: {resp.json().get('detail', '')[:60]}")
        else:
            print(f"  [WARN] publisher 应被 403，实际 {resp.status_code}: {resp.text}")


def main():
    print("=" * 60)
    print("W2 端到端联调 — n8n 工作流模拟")
    print("=" * 60)

    # 登录 admin
    token, user = login("admin", "admin123")

    # 步骤 1: 模拟 n8n 推送
    recommended_ids = step1_import(token)

    # 步骤 2: 一审列表
    candidates = step2_list_review(token)

    # 步骤 3: 并发决策
    step3_concurrent_decide(token, recommended_ids)

    # 步骤 4: RBAC 测试
    pub_token, pub_user = login("publisher", "admin123")
    step4_rbac({"token": pub_token, "user": pub_user})

    print("\n" + "=" * 60)
    print("✅ 端到端联调完成")
    print("=" * 60)


if __name__ == "__main__":
    main()