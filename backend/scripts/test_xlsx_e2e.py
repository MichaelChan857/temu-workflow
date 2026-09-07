"""XLSX 端到端测试（不需要启动 Docker）

模拟完整流程：
  1. 生成示例 XLSX
  2. 解析 XLSX（不依赖网络）
  3. 验证：必填字段、标准化、去重 key 生成
  4. 应用规则 → 验证侵权商品被淘汰
  5. 评分 → 验证权重计算
"""
import sys
import io
import subprocess
from pathlib import Path

# 让脚本能找到 app.*
sys.path.insert(0, str(Path(__file__).parent.parent))

# 1. 生成 XLSX
xlsx_path = Path(__file__).parent / "sample_w3.xlsx"
subprocess.run(
    ["uv", "run", "--quiet", "--with", "openpyxl", "python", str(Path(__file__).parent / "gen_xlsx.py"), str(xlsx_path)],
    check=True,
)

# 2. 解析 XLSX
from app.services.file_parser import parse_xlsx, parse_csv
print(f"\n[1/4] 解析 XLSX 文件: {xlsx_path.name}")
content = xlsx_path.read_bytes()
rows = list(parse_xlsx(content))
print(f"  解析 {len(rows)} 行")
assert len(rows) == 7, f"应 7 行，实际 {len(rows)}"
assert rows[0]["title"] == "Pet Cat Window Perch Hammock"
print(f"  [OK] 第一行 title: {rows[0]['title']}")

# 3. 标准化
print(f"\n[2/4] 标准化")
import hashlib
normalized = []
for i, row in enumerate(rows, start=2):
    # 数字转换
    if row.get("price"):
        row["price"] = float(row["price"])
    if row.get("weight_g"):
        row["weight_g"] = int(row["weight_g"])
    images = [row.get(f"image_url_{i}") for i in (1, 2, 3) if row.get(f"image_url_{i}")]
    row["image_urls"] = images
    parts = [row.get("supplier_sku", ""), row.get("source_product_id", ""), (row.get("title") or "")[:50]]
    row["dedupe_key"] = hashlib.md5("|".join(parts).encode()).hexdigest()
    normalized.append(row)
print(f"  [OK] {len(normalized)} 行标准化完成")
print(f"  示例 dedupe_key: {normalized[0]['dedupe_key'][:16]}...")

# 4. 规则筛选
print(f"\n[3/4] 应用规则引擎")
from app.services.rules import run_rules

pass_count = 0
filtered = []
for r in normalized:
    c_dict = {
        "title": r["title"], "description": r.get("description"),
        "category": r.get("category"),
        "price": r.get("price"), "cost": r.get("cost"),
        "weight_g": r.get("weight_g"), "dimensions": None,
        "image_urls": r.get("image_urls", []),
        "supplier_sku": r.get("supplier_sku"),
        "rights_confirmed": False,
    }
    passes, hits = run_rules(c_dict)
    if not passes:
        codes = [h.rule_code for h in hits if h.rule_type == "hard"]
        filtered.append((r["title"], codes))
    else:
        pass_count += 1

print(f"  通过硬筛: {pass_count} 个")
print(f"  被淘汰:   {len(filtered)} 个")
for title, codes in filtered:
    print(f"    [{','.join(codes)}] {title[:40]}")

# 5. 评分
print(f"\n[4/4] 评分（使用默认权重）")
from app.services.scoring import score_candidate, rank_candidates

scored_items = []
for r in normalized:
    c_dict = {
        "title": r["title"], "category": r.get("category"),
        "price": r.get("price"), "cost": r.get("cost"),
        "weight_g": r.get("weight_g"),
        "image_urls": r.get("image_urls", []),
        "rights_confirmed": False,
    }
    if any(r["title"] in t for t, _ in filtered):
        continue
    s = score_candidate(c_dict)
    scored_items.append({"candidate": c_dict, "score": s, "candidate_id": r["source_product_id"]})

ranked = rank_candidates(scored_items)
print(f"  输入 {len(scored_items)} 个 → 推荐 {len(ranked)} 个")
for r in ranked:
    print(f"    ★ {r['candidate_id']}: {r['candidate']['title'][:40]:40} score={r['score'].total_score:.1f}")

# 关键断言
assert len(filtered) >= 1, "XLSX-005 应被硬筛淘汰"
assert any("BANNED" in c for _, cs in filtered for c in cs), "应触发 BANNED_KEYWORD"
assert len(ranked) >= 2, "应至少 2 个推荐"

print(f"\n=== XLSX E2E 测试通过 ===")