"""真实 API 端到端调用 — 7 步演示

前置：后端服务在 8000 端口运行（SQLite 模式）
"""
import sys
import json
import time
from pathlib import Path
import httpx

API = "http://127.0.0.1:8000"

def step(n, title):
    print(f"\n[STEP {n}] {title}")
    print("-" * 70)

def show(label, data):
    if isinstance(data, (dict, list)):
        s = json.dumps(data, ensure_ascii=False, indent=2)
        if len(s) > 400:
            s = s[:400] + "..."
        print(f"  [{label}]\n{s}")
    else:
        print(f"  [{label}] {data}")


def main():
    print("=" * 70)
    print("  Temu Workflow MVP - 真实 API 端到端演示（SQLite 后端）")
    print("=" * 70)

    with httpx.Client(timeout=30.0) as client:

        # ========== STEP 1: 登录（admin） ==========
        step(1, "登录 admin 用户（拿 JWT）")
        r = client.post(f"{API}/api/v1/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        if r.status_code != 200:
            # 用户不存在 → 提示先 seed
            print(f"  [WARN] 登录失败 {r.status_code}: {r.text[:200]}")
            print(f"  请先执行: uv run python scripts/seed_users.py")
            return
        token = r.json()["access_token"]
        user = r.json()["user"]
        show("user", user)
        H = {"Authorization": f"Bearer {token}"}

        # ========== STEP 2: 查看一审列表 ==========
        step(2, "查询一审列表（当前为空）")
        r = client.get(f"{API}/api/v1/candidates?status=first_review&limit=5", headers=H)
        show("status", r.status_code)
        show("candidates", r.json()[:3] if isinstance(r.json(), list) else r.json())

        # ========== STEP 3: 导入示例 CSV（10 个候选）============
        step(3, "导入示例 CSV（10 候选）")
        csv_path = Path(__file__).parent / "sample_candidates.csv"
        with open(csv_path, "rb") as f:
            r = client.post(
                f"{API}/api/v1/import/file",
                files={"file": ("sample.csv", f, "text/csv")},
                data={"shop_id": "default"},
                headers=H,
            )
        result = r.json()
        show("status", r.status_code)
        show("import_result", {k: v for k, v in result.items() if k != "recommended_ids"})

        # ========== STEP 4: 再次查询一审列表（应该有5 个高分）============
        step(4, "再次查询一审列表（应有5 个推荐）")
        r = client.get(f"{API}/api/v1/candidates?status=first_review&limit=10", headers=H)
        candidates = r.json()
        show("count", len(candidates))
        if candidates:
            print(f"\n  前 5 个推荐（按分数降序）:")
            for c in candidates[:5]:
                print(f"    [{c['total_score']:.1f}] {c['title'][:50]:50s} ${c['price']}")

        # ========== STEP 5: 取第 1 个候选做详情 ==========
        if candidates:
            step(5, "获取第 1 个候选详情")
            cid = candidates[0]["id"]
            r = client.get(f"{API}/api/v1/candidates/{cid}", headers=H)
            detail = r.json()
            show("dimension_scores", detail.get("dimension_scores"))
            show("reason", detail.get("reason"))
            show("risks", detail.get("risks"))
            show("filter_hits", detail.get("filter_hits"))

            # ========== STEP 6: 一审通过 ==========
            step(6, f"一审通过 {cid[:8]}...")
            # 不带 expected_version（让后端不强校验）
            r = client.post(
                f"{API}/api/v1/candidates/{cid}/decision",
                json={"decision": "approve", "comment": "demo 通过"},
                headers=H,
            )
            show("status", r.status_code)
            show("result", r.json())

            # ========== STEP 7: AI 生成标题（找listing）============
            step(7, "查找生成的 listing + AI 文案")
            r = client.get(f"{API}/api/v1/listings?limit=5", headers=H)
            listings = r.json()
            if listings:
                lid = listings[0]["id"]
                # AI 生成
                r = client.post(
                    f"{API}/api/v1/listings/generate",
                    json={"candidate_id": cid},
                    headers=H,
                )
                show("ai_status", r.status_code)
                if r.status_code == 200:
                    ai = r.json()
                    show("title", ai.get("title"))
                    show("bullet_points", ai.get("bullet_points"))
                    show("description", (ai.get("description") or "")[:200])

                    # ========== STEP 8: 人工编辑 ==========
                    step(8, "人工编辑 listing（改标题）")
                    r = client.put(
                        f"{API}/api/v1/listings/{lid}",
                        json={"title": "Pet Toy - Premium Quality (Edited)", "change_note": "demo edit"},
                        headers=H,
                    )
                    show("status", r.status_code)
                    show("version", r.json().get("version"))

                    # ========== STEP 9: 进入二审 ==========
                    step(9, "二审校验 + 通过 + 冻结快照")
                    r = client.get(f"{API}/api/v1/listings/{lid}/second-review", headers=H)
                    sr = r.json()
                    show("checks", sr.get("checks"))

                    if sr["checks"]["can_pass"]:
                        r = client.post(
                            f"{API}/api/v1/listings/{lid}/second-review",
                            json={"decision": "approve", "comment": "demo 二审通过"},
                            headers=H,
                        )
                        show("status", r.status_code)
                        show("result", r.json())
                    else:
                        print(f"  [WARN] 二审校验失败: {sr['checks']['errors']}")

                    # ========== STEP 10: 发起发布 ==========
                    step(10, "发起发布（mock Temu 适配器）")
                    r = client.post(
                        f"{API}/api/v1/publish/start",
                        json={"listing_id": lid, "auto_execute": True},
                        headers=H,
                    )
                    show("status", r.status_code)
                    show("result", r.json())

                    # 等几秒看 worker 处理
                    print("\n  等待 5 秒让 Worker 处理...")
                    time.sleep(5)

                    r = client.get(f"{API}/api/v1/publish/jobs/{r.json()['job_id']}", headers=H)
                    show("job_status", r.json())

        # ========== STEP 11: 看告警中心 ==========
        step(11, "查看告警")
        r = client.get(f"{API}/api/v1/alerts", headers=H)
        alerts = r.json()
        show("count", len(alerts))
        if alerts:
            for a in alerts[:3]:
                print(f"    [{a['level']}] {a['title']}")

        # ========== STEP 12: 看评分配置 ==========
        step(12, "查看当前评分配置")
        r = client.get(f"{API}/api/v1/scoring-config/active", headers=H)
        show("active_config", r.json())

    print("\n" + "=" * 70)
    print("  演示完成！")
    print("=" * 70)
    print("\n  你可以浏览器访问:")
    print(f"    http://127.0.0.1:8000/docs    ← Swagger UI")
    print(f"    http://127.0.0.1:8000/api/v1/candidates    ← 候选列表")
    print(f"    http://127.0.0.1:8000/api/v1/listings    ← 资料列表")


if __name__ == "__main__":
    main()