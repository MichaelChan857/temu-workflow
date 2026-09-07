"""模拟 n8n workflow 的 Python 端到端 demo

等价于 n8n 7 节点工作流的执行:
  触发 → 读 CSV → 解析 → POST /import/json → IF(候选不足?) → 告警/通知

用于验证 n8n 调后端整条链路的连通性，绕开 n8n 2.x webhook 注册 bug。
"""
import sys
import csv
import json
from pathlib import Path
import httpx
from io import StringIO

API = "http://127.0.0.1:8000"
CSV_PATH = Path(__file__).parent.parent.parent / "n8n" / "imports" / "daily_sample.csv"


def login() -> str:
    r = httpx.post(f"{API}/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    r.raise_for_status()
    return r.json()["access_token"]


def read_csv() -> str:
    """节点 2: 读 CSV 文件"""
    print(f"[1] 读 CSV: {CSV_PATH}")
    return CSV_PATH.read_text(encoding="utf-8")


def parse_csv(text: str) -> list[dict]:
    """节点 3: 解析 CSV → candidates"""
    print(f"[2] 解析 CSV 行")
    # 跳过以 # 开头的注释行（DictReader 会把第1个非空行当 header）
    lines = [l for l in text.splitlines() if l and not l.startswith("#")]
    reader = csv.DictReader(StringIO("\n".join(lines)))
    cands = []
    for row in reader:
        obj = dict(row)
        # 数字转换
        if obj.get("price"): obj["price"] = float(obj["price"])
        if obj.get("cost"): obj["cost"] = float(obj["cost"])
        if obj.get("weight_g"): obj["weight_g"] = int(obj["weight_g"])
        # 拼 image_urls
        obj["image_urls"] = []
        for n in range(1, 4):
            k = f"image_url_{n}"
            if obj.get(k):
                obj["image_urls"].append(obj[k])
                del obj[k]
        cands.append(obj)
    return cands


def call_backend(token: str, candidates: list[dict]) -> dict:
    """节点 4: POST /api/v1/import/json"""
    print(f"[3] 推送 {len(candidates)} 候选到后端")
    r = httpx.post(
        f"{API}/api/v1/import/json",
        json={"candidates": candidates, "source": "n8n_demo"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    if r.status_code != 200:
        print(f"  [ERROR] {r.status_code}: {r.text[:500]}")
    r.raise_for_status()
    return r.json()


def check_count(result: dict) -> bool:
    """节点 5: IF 候选不足 < 20？"""
    recommended = result.get("recommended", 0)
    print(f"[4] 检查推荐数: {recommended} (阈值 20)")
    return recommended < 20


def send_alert(token: str, recommended: int) -> dict:
    """节点 6: POST /api/v1/alerts/send"""
    msg = f"今日推荐 {recommended} 个，少于默认 20 个"
    print(f"[5] 发送告警: {msg}")
    r = httpx.post(
        f"{API}/api/v1/alerts/send",
        json={"level": "warning", "title": "Temu 候选不足", "message": msg, "source": "n8n_demo"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    return r.json()


def notify_reviewers(token: str, batch_id: str, recommended: int) -> dict:
    """节点 7: POST /api/v1/notifications/first-review-ready"""
    print(f"[6] 通知一审: batch={batch_id[:8]}... recommended={recommended}")
    r = httpx.post(
        f"{API}/api/v1/notifications/first-review-ready",
        json={"batch_id": batch_id, "recommended_count": recommended},
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    return r.json()


def main():
    print("=" * 70)
    print("  n8n workflow 等价端到端 Demo (Python 实现)")
    print("=" * 70)

    # 登录
    print("\n[setup] admin 登录")
    token = login()
    print(f"  ✓ token 长度 {len(token)}")

    # 节点 1+2+3: 触发 → 读 CSV → 解析
    # 等价于 n8n workflow 的「每天 06:00 触发 → 读当日 CSV → 解析 CSV」
    text = read_csv()
    cands = parse_csv(text)

    # 节点 4: 推送到后端
    result = call_backend(token, cands)
    print(f"  ✓ 后端返回: batch_id={result.get('batch_id', '?')[:8]}..., recommended={result.get('recommended', 0)}")

    # 节点 5: IF 分支
    if check_count(result):
        # 节点 6: 发送告警
        send_alert(token, result.get("recommended", 0))
    else:
        # 节点 7: 通知一审
        notify_reviewers(token, result.get("batch_id", ""), result.get("recommended", 0))

    print("\n" + "=" * 70)
    print("  ✓ ALL OK — n8n workflow 等价流程跑通")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())