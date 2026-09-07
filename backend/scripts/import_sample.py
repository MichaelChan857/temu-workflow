"""导入示例 CSV — 端到端验证脚本

用法：
    docker compose exec backend python scripts/import_sample.py
"""
import httpx
import sys
from pathlib import Path

API_BASE = "http://localhost:8000"
CSV_FILE = Path(__file__).parent / "sample_candidates.csv"


def main():
    if not CSV_FILE.exists():
        print(f"ERROR: {CSV_FILE} not found")
        sys.exit(1)

    print(f"[1/3] Uploading {CSV_FILE} ({CSV_FILE.stat().st_size} bytes)...")
    with open(CSV_FILE, "rb") as f:
        resp = httpx.post(
            f"{API_BASE}/api/v1/import/csv",
            files={"file": ("sample_candidates.csv", f, "text/csv")},
            timeout=60.0,
        )

    if resp.status_code != 200:
        print(f"ERROR {resp.status_code}: {resp.text}")
        sys.exit(1)

    result = resp.json()
    print(f"[2/3] Import complete. Batch: {result['batch_id']}")
    print(f"   Imported: {result['imported']}")
    print(f"   Errors:   {result['errors']}")
    print(f"   Valid:    {result['valid']}")
    print(f"   Deduped:  {result['deduped']}")
    print(f"   Filtered: {result['filtered_out']}")
    print(f"   Scored:   {result['scored']}")
    print(f"   Recommended: {result['recommended']}")
    print()
    print(f"[3/3] Open http://localhost:3000 to start first review")
    print(f"      Recommended IDs: {result['recommended_ids'][:5]}")


if __name__ == "__main__":
    main()