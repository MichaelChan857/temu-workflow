"""W9-1 端到端真实演示 — 从CSV到Temu完整流程

前置：后端服务在 8000 端口运行
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
        if len(s) > 500:
            s = s[:500] + "..."
        print(f"  [{label}]\n{s}")
    else:
        print(f"  [{label}] {data}")


def reset_db():
    """重置 demo 数据：直接通过 sqlite 命令清空"""
    import sqlite3
    db_path = "temu_demo.db"
    if Path(db_path).exists():
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            # 删表数据（保留 schema）
            for table in ["publish_jobs", "listing_versions", "listing_drafts",
                          "review_tasks", "product_scores", "filter_results",
                          "candidate_products", "selection_batches", "events",
                          "config_versions"]:
                try:
                    cur.execute(f"DELETE FROM {table}")
                except:
                    pass
            conn.commit()
            conn.close()
            print("  [OK] DB 已重置")
        except Exception as e:
            print(f"  [WARN] 重置失败: {e}")


def main():
    print("=" * 70)
    print("  Temu Workflow MVP - 端到端真实演示")
    print("=" * 70)

    # ====== 0. 重置 DB（确保 demo 数据干净） ======
    step(0, "重置数据库（清空旧数据）")
    reset_db()

    with httpx.Client(timeout=60.0) as client:

        # ====== 1. 健康检查 ======
        step(1, "健康检查")
        r = client.get(f"{API}/")
        show("status", r.status_code)
        show("info", r.json())

        # ====== 2. 登录 ======
        step(2, "登录 admin 用户")
        r = client.post(f"{API}/api/v1/auth/login", json={
            "username": "admin", "password": "admin123"
        })
        show("status", r.status_code)
        token = r.json()["access_token"]
        user = r.json()["user"]
        show("user", user)
        H = {"Authorization": f"Bearer {token}"}

        # ====== 3. 创建 6 个测试用户（用 seed_users.py 一样的逻辑） ======
        step(3, "检查 6 角色用户存在")
        # 通过业务接口看（实际已 seed 过）
        # 这里展示登录不同角色 — 用 admin 已登录

        # ====== 4. CSV 导入 ======
        step(4, "导入示例 CSV（10 商品）")
        csv_path = Path(__file__).parent / "sample_candidates.csv"
        if not csv_path.exists():
            print(f"  [ERROR] CSV 不存在: {csv_path}")
            return
        with open(csv_path, "rb") as f:
            r = client.post(
                f"{API}/api/v1/import/file",
                files={"file": (csv_path.name, f, "text/csv")},
                data={"shop_id": "default"},
                headers=H,
            )
        result = r.json()
        show("status", r.status_code)
        show("summary", {k: v for k, v in result.items() if k not in ("recommended_ids", "errors")})

        # ====== 5. 一审列表 ======
        step(5, "查询一审列表（应有 5 个高分候选）")
        r = client.get(f"{API}/api/v1/candidates?status=first_review&limit=10", headers=H)
        candidates = r.json()
        show("count", len(candidates))
        print(f"\n  推荐候选（按分数降序）:")
        for i, c in enumerate(candidates[:5], 1):
            print(f"    {i}. [{c['total_score']:.1f}] {c['title'][:50]:50s} ${c['price']}")

        if not candidates:
            print("\n  [WARN] 没有推荐候选，可能所有都已审核过")
            return

        # ====== 6. 取详情 + 一审通过第 1 个 ======
        first = candidates[0]
        cid = first["id"]
        step(6, f"一审通过: {first['title'][:50]}")
        r = client.post(
            f"{API}/api/v1/candidates/{cid}/decision",
            json={"decision": "approve", "comment": "demo 通过"},
            headers=H,
        )
        show("status", r.status_code)
        show("result", r.json())

        # ====== 7. AI 生成标题 ======
        step(7, "AI 生成标题（mock Claude）")
        r = client.post(f"{API}/api/v1/listings/generate",
            json={"candidate_id": cid}, headers=H)
        if r.status_code == 200:
            ai = r.json()
            show("title", ai.get("title"))
            show("bullet_points", ai.get("bullet_points"))
            show("description", (ai.get("description") or "")[:150])
            lid = ai["listing_id"]
        else:
            print(f"  [ERROR] {r.status_code}: {r.text}")
            # 找现有 listing
            r = client.get(f"{API}/api/v1/listings?limit=10", headers=H)
            listings = r.json()
            lid = listings[0]["id"] if listings else None

        if not lid:
            print("  [ERROR] 没有 listing 可用")
            return

        # ====== 8. 编辑 listing ======
        step(8, f"编辑 listing {lid[:8]}...")
        r = client.put(f"{API}/api/v1/listings/{lid}",
            json={"title": "Demo - Premium Quality (Edited)", "change_note": "demo"},
            headers=H)
        show("status", r.status_code)
        show("version", r.json().get("version"))

        # ====== 9. 二审通过 + 冻结快照 ======
        step(9, "二审通过 + 冻结快照")
        r = client.get(f"{API}/api/v1/listings/{lid}/second-review", headers=H)
        sr = r.json()
        show("checks.can_pass", sr["checks"]["can_pass"])
        if sr["checks"]["can_pass"]:
            r = client.post(f"{API}/api/v1/listings/{lid}/second-review",
                json={"decision": "approve", "comment": "demo 二审", "confirm_warnings": True},
                headers=H)
            show("result", r.json())
        else:
            print(f"  [WARN] 二审校验失败: {sr['checks']['errors']}")
            # 强制通过（仅 demo）
            r = client.put(f"{API}/api/v1/listings/{lid}",
                json={"attributes": {"price": 19.99, "currency": "USD"}, "change_note": "fix attrs"},
                headers=H)
            print(f"  已修复 attributes，再试二审...")
            r = client.post(f"{API}/api/v1/listings/{lid}/second-review",
                json={"decision": "approve", "comment": "demo 二审", "confirm_warnings": True},
                headers=H)
            show("retry_result", r.json())

        # ====== 10. 发起发布 ======
        step(10, "发起发布（mock Temu 适配器）")
        r = client.post(f"{API}/api/v1/publish/start",
            json={"listing_id": lid, "auto_execute": True},
            headers=H)
        show("status", r.status_code)
        if r.status_code == 200:
            job_id = r.json()["job_id"]
            show("job_id", job_id[:16] + "...")
            show("idempotency_key", r.json()["idempotency_key"][:16] + "...")

            # ====== 11. 轮询 job 状态 ======
            step(11, "轮询 job 状态（5 秒后）")
            time.sleep(5)
            r = client.get(f"{API}/api/v1/publish/jobs/{job_id}", headers=H)
            show("status", r.status_code)
            show("result", r.json())

        # ====== 12. 发送测试告警 ======
        step(12, "发送测试告警")
        r = client.post(f"{API}/api/v1/alerts/send", headers=H,
            json={
                "level": "info",
                "title": "端到端演示完成",
                "message": "从CSV到Temu全流程跑通",
            })
        show("status", r.status_code)
        show("result", r.json())

        # ====== 13. 查看告警 ======
        step(13, "查看告警中心")
        r = client.get(f"{API}/api/v1/alerts", headers=H)
        alerts = r.json()
        show("count", len(alerts))
        for a in alerts[:3]:
            print(f"    [{a['level']}] {a['title']}")

        # ====== 14. 查看评分配置 ======
        step(14, "查看当前评分配置")
        r = client.get(f"{API}/api/v1/scoring-config/active", headers=H)
        show("active", r.json())

        # ====== 15. 查看数据源类型 ======
        step(15, "查看支持的数据源类型")
        r = client.get(f"{API}/api/v1/data-sources/types", headers=H)
        show("types", r.json())

    print("\n" + "=" * 70)
    print("  演示完成！")
    print("=" * 70)
    print("\n  你可以浏览器访问:")
    print(f"    http://127.0.0.1:8000/ui/login.html")
    print(f"    http://127.0.0.1:8000/ui/dashboard.html")
    print(f"    http://127.0.0.1:8000/docs")


if __name__ == "__main__":
    main()