# -*- coding: utf-8 -*-
"""W10-5 完整工作流演示 - 一次性把全流程跑通"""
import sys
import json
import time
import sqlite3
import subprocess
import httpx
from pathlib import Path

API = "http://127.0.0.1:8000"
DB = Path("temu_demo.db")
CSV = Path("scripts/sample_candidates.csv")


def step(n, title):
    print()
    print(f"[STEP {n:2d}] {title}")
    print("-" * 70)


def show(label, data, max_len=400):
    s = json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else str(data)
    if len(s) > max_len:
        s = s[:max_len] + "..."
    print(f"  [{label}] {s}")


def ensure_server():
    try:
        r = httpx.get(API + "/", timeout=3)
        if r.status_code == 200:
            return True
    except:
        pass
    print("  [INFO] 服务未运行,正在启动...")
    subprocess.run(["cmd", "/c", "taskkill", "/F", "/IM", "python.exe", "/T"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    subprocess.Popen(
        ["uv", "run", "--quiet", "--with", "aiosqlite", "--with", "pydantic-settings",
         "--with", "fastapi", "--with", "sqlalchemy", "--with", "pyjwt", "--with", "httpx",
         "--with", "openpyxl", "--with", "uvicorn", "--with", "python-multipart",
         "--with", "loguru", "python", "scripts/run_dev.py"],
        stdout=open("/tmp/devserver.log", "w"), stderr=subprocess.STDOUT,
    )
    for _ in range(15):
        time.sleep(2)
        try:
            if httpx.get(API + "/", timeout=2).status_code == 200:
                print("  [OK] 服务已启动")
                return True
        except:
            continue
    print("  [ERROR] 服务启动失败")
    return False


def reset_db():
    """重置业务数据（保留 users / shops / data_sources）"""
    if DB.exists():
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()
        for table in ["publish_jobs", "listing_versions", "listing_drafts",
                      "review_tasks", "product_scores", "filter_results",
                      "candidate_products", "selection_batches", "events",
                      "config_versions"]:
            try:
                cur.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        conn.close()
        print("  [OK] 业务数据已重置 (保留 6 个用户)")


def main():
    print("=" * 70)
    print("  Temu Workflow MVP - 完整工作流演示 (15 步)")
    print("=" * 70)

    if not ensure_server():
        sys.exit(1)

    with httpx.Client(timeout=60.0) as client:

        # 1. 登录
        step(1, "登录 admin 用户")
        r = client.post(f"{API}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"})
        show("status", r.status_code)
        if r.status_code != 200:
            print(f"  [ERROR] {r.text}")
            print("  [TIP] 请先运行 seed_users.py 创建 admin")
            return
        token = r.json()["access_token"]
        H = {"Authorization": f"Bearer {token}"}

        # 2. 验证 6 用户
        step(2, "验证 6 角色用户登录")
        roles = ["admin", "operator", "editor", "reviewer", "publisher", "readonly"]
        for r2 in roles:
            r = client.post(f"{API}/api/v1/auth/login",
                json={"username": r2, "password": "admin123"})
            print(f"    [{'OK' if r.status_code==200 else 'X'}] {r2}")

        # 3. 重置数据
        step(3, "重置业务数据 (保留用户)")
        reset_db()

        # 4. 导入 CSV
        step(4, "导入示例 CSV (10 个候选)")
        with open(CSV, "rb") as f:
            r = client.post(
                f"{API}/api/v1/import/file",
                files={"file": (CSV.name, f, "text/csv")},
                data={"shop_id": "default"},
                headers=H,
            )
        result = r.json()
        show("status", r.status_code)
        show("batch_id", result["batch_id"])
        print(f"    导入: {result['imported']}, 有效: {result['valid']}, "
              f"淘汰: {result['filtered_out']}, 评分: {result['scored']}, "
              f"推荐: {result['recommended']}")

        # 5. 一审列表
        step(5, "查询一审列表")
        r = client.get(f"{API}/api/v1/candidates?status=first_review&limit=10", headers=H)
        cands = r.json()
        print(f"    推荐候选 ({len(cands)}):")
        for i, c in enumerate(cands[:5], 1):
            print(f"    {i}. [{c['total_score']:5.1f}] {c['title'][:50]:50s} ${c['price']}")

        if not cands:
            return

        # 6. operator 一审
        step(6, "operator 一审通过 (第 1 个候选)")
        r = client.post(f"{API}/api/v1/auth/login",
            json={"username": "operator", "password": "admin123"})
        op_H = {"Authorization": f"Bearer {r.json()['access_token']}"}
        cid = cands[0]["id"]
        r = client.post(f"{API}/api/v1/candidates/{cid}/decision",
            json={"decision": "approve", "comment": "operator 通过"},
            headers=op_H)
        show("status", r.status_code)
        show("new_status", r.json().get("new_status"))

        # 7. editor AI 生成
        step(7, "editor AI 生成标题/卖点/描述")
        r = client.post(f"{API}/api/v1/auth/login",
            json={"username": "editor", "password": "admin123"})
        ed_H = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = client.post(f"{API}/api/v1/listings/generate",
            json={"candidate_id": cid}, headers=ed_H)
        if r.status_code != 200:
            print(f"  [ERROR] {r.text[:200]}")
            # 找现有 listing
            r = client.get(f"{API}/api/v1/listings?limit=5", headers=ed_H)
            lid = r.json()[0]["id"] if r.json() else None
        else:
            ai = r.json()
            lid = ai["listing_id"]
            print(f"    标题: {ai.get('title')}")
            bps = ai.get("bullet_points", [])
            print(f"    卖点 ({len(bps)} 条):")
            for bp in bps:
                print(f"      - {bp}")
            print(f"    描述: {ai.get('description', '')[:80]}...")

        if not lid:
            print("  [FATAL] 无 listing 可用")
            return

        # 8. editor 编辑
        step(8, f"editor 编辑 listing {lid[:8]}...")
        r = client.put(f"{API}/api/v1/listings/{lid}",
            json={"title": "Premium Quality (Edited by editor)", "change_note": "demo"},
            headers=ed_H)
        show("version", r.json().get("version"))

        # 9. reviewer 二审校验
        step(9, "reviewer 二审校验")
        r = client.post(f"{API}/api/v1/auth/login",
            json={"username": "reviewer", "password": "admin123"})
        rev_H = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = client.get(f"{API}/api/v1/listings/{lid}/second-review", headers=rev_H)
        checks = r.json()["checks"]
        print(f"    can_pass: {checks['can_pass']}")
        if checks.get("warnings"): print(f"    warnings: {checks['warnings']}")
        if checks.get("errors"): print(f"    errors: {checks['errors']}")

        # 10. reviewer 二审通过
        step(10, "reviewer 二审通过 + 冻结快照")
        r = client.post(f"{API}/api/v1/listings/{lid}/second-review",
            json={"decision": "approve", "confirm_warnings": True, "comment": "reviewer"},
            headers=rev_H)
        show("status", r.status_code)
        show("result", r.json())

        # 11. publisher 发布
        step(11, "publisher 发起发布 (调 mock Temu 适配器)")
        r = client.post(f"{API}/api/v1/auth/login",
            json={"username": "publisher", "password": "admin123"})
        pub_H = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = client.post(f"{API}/api/v1/publish/start",
            json={"listing_id": lid, "auto_execute": True}, headers=pub_H)
        show("status", r.status_code)
        if r.status_code != 200:
            print(f"  [ERROR] {r.text[:200]}")
            return
        job = r.json()
        job_id = job["job_id"]
        print(f"    job_id: {job_id[:16]}...")
        print(f"    idempotency_key: {job['idempotency_key'][:16]}...")

        # 12. 轮询
        step(12, "轮询发布结果 (5 秒)")
        time.sleep(5)
        r = client.get(f"{API}/api/v1/publish/jobs/{job_id}", headers=H)
        result = r.json()
        print(f"    status: {result.get('status')}")
        print(f"    platform_status: {result.get('platform_status')}")
        if result.get("platform_product_id"):
            print(f"    平台商品 ID: {result['platform_product_id']}")
        if result.get("last_error"):
            print(f"    [WARN] {result['last_error']}")

        # 13. listing 最终状态
        step(13, f"listing {lid[:8]}... 最终状态")
        r = client.get(f"{API}/api/v1/listings/{lid}", headers=H)
        final = r.json()
        print(f"    标题: {final.get('title')}")
        print(f"    状态: {final.get('status')}")
        print(f"    版本: v{final.get('version')}")
        print(f"    快照: {'已冻结' if final.get('has_snapshot') else '未冻结'}")

        # 14. 发送告警
        step(14, "publisher 发送测试告警")
        r = client.post(f"{API}/api/v1/alerts/send", headers=pub_H,
            json={"level": "info", "title": "演示完成",
                  "message": f"listing {lid[:8]} 已成功发布"})
        show("status", r.status_code)

        # 15. 统计
        step(15, "最终业务数据统计")
        cands = client.get(f"{API}/api/v1/candidates?limit=200", headers=H).json()
        lsts = client.get(f"{API}/api/v1/listings?limit=200", headers=H).json()
        alerts = client.get(f"{API}/api/v1/alerts", headers=H).json()

        cstatus = {}
        for c in cands:
            cstatus[c["status"]] = cstatus.get(c["status"], 0) + 1
        lstatus = {}
        for l in lsts:
            lstatus[l["status"]] = lstatus.get(l["status"], 0) + 1

        print(f"    候选 ({len(cands)}): {dict(cstatus)}")
        print(f"    资料 ({len(lsts)}): {dict(lstatus)}")
        print(f"    告警: {len(alerts)} 条")

    print()
    print("=" * 70)
    print("  演示完成!")
    print("=" * 70)
    print()
    print(f"  浏览器访问:")
    print(f"    http://127.0.0.1:8000/ui/login.html")
    print(f"    http://127.0.0.1:8000/ui/dashboard.html")


if __name__ == "__main__":
    main()