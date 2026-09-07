"""Temu Workflow 编排器（n8n 替代）

无需 n8n UI / Docker，纯 Python + asyncio 实现同样功能：
  - 定时触发（cron 风格）
  - HTTP 调用（调我们的 FastAPI 后端）
  - 条件分支（推荐数 < 20 → 告警）
  - 错误重试 + 告警

3 个工作流：
  1. daily_import.py — 每日导入 CSV
  2. auto_publish.py — 每日自动发布
  3. monitor_alerts.py — 每 10 分钟检查告警
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Python 3.13 兼容
UTC = timezone.utc

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("orchestrator")


# ============ 配置 ============
API_BASE = os.getenv("TEMU_API_BASE", "http://127.0.0.1:8000")
USERNAME = os.getenv("TEMU_USERNAME", "admin")
PASSWORD = os.getenv("TEMU_PASSWORD", "admin123")
CSV_PATH = os.getenv("TEMU_CSV_PATH", "")
TOKEN_CACHE = {"token": None, "expires_at": None}


# ============ 通用工具 ============
async def login() -> str:
    """登录拿 JWT（带缓存）"""
    if TOKEN_CACHE["token"] and TOKEN_CACHE["expires_at"] > datetime.now(UTC):
        return TOKEN_CACHE["token"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{API_BASE}/api/v1/auth/login",
            json={"username": USERNAME, "password": PASSWORD},
        )
        r.raise_for_status()
        data = r.json()
        TOKEN_CACHE["token"] = data["access_token"]
        TOKEN_CACHE["expires_at"] = datetime.now(UTC) + timedelta(hours=7)
        log.info(f"登录成功: {USERNAME}")
        return data["access_token"]


async def api(path: str, method: str = "GET", **kwargs) -> dict:
    """调用后端 API"""
    token = await login()
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)
        r.raise_for_status()
        return r.json()


async def send_alert(level: str, title: str, message: str):
    """发送告警"""
    try:
        await api("/api/v1/alerts/send", method="POST", json={
            "level": level,
            "title": title,
            "message": message,
        })
        log.info(f"告警已发送: [{level}] {title}")
    except Exception as e:
        import traceback
        log.error(f"发送告警失败: {e!r}\n{traceback.format_exc()}")


# ============ 工作流 1: 每日导入 CSV ============
async def daily_import_workflow(csv_path: str | None = None):
    """每日定时导入候选商品

    触发：每日 06:00
    步骤：
      1. 读取 CSV 文件
      2. POST /api/v1/import/file
      3. 检查结果：
         - 推荐数 < 20 → 告警
         - 失败数 > 30% → 告警
      4. 发送告警到告警中心
    """
    log.info("=" * 60)
    log.info("[Workflow 1] 每日导入")
    log.info("=" * 60)

    csv_path = csv_path or CSV_PATH or str(
        Path(__file__).parent.parent / "backend" / "scripts" / "sample_candidates.csv"
    )

    if not Path(csv_path).exists():
        await send_alert("error", "导入失败", f"CSV 文件不存在: {csv_path}")
        return {"status": "failed", "reason": "csv not found"}

    try:
        with open(csv_path, "rb") as f:
            result = await api(
                "/api/v1/import/file",
                method="POST",
                files={"file": (Path(csv_path).name, f, "text/csv")},
                data={"shop_id": "default"},
            )

        log.info(f"导入完成: batch={result['batch_id'][:8]}...")
        log.info(f"  导入: {result['imported']}, 推荐: {result['recommended']}")
        log.info(f"  错误: {len(result.get('errors', []))}, 淘汰: {result['filtered_out']}")

        # 检查推荐数
        recommended = result.get("recommended", 0)
        if recommended < 20:
            await send_alert(
                "warning",
                "Temu 候选不足",
                f"今日推荐 {recommended} 个，少于目标 20 个",
            )

        # 检查错误数
        error_count = len(result.get("errors", []))
        if result["imported"] > 0 and error_count / result["imported"] > 0.3:
            await send_alert(
                "error",
                "导入错误率过高",
                f"错误数 {error_count} / 导入 {result['imported']} ({error_count/result['imported']*100:.0f}%)",
            )

        return {"status": "ok", "result": result}

    except Exception as e:
        log.exception("导入失败")
        await send_alert("error", "导入异常", str(e))
        return {"status": "exception", "error": str(e)}


# ============ 工作流 2: 自动发布 ============
async def auto_publish_workflow():
    """每日自动发布：找 ready_to_publish 的 listing 并发布

    触发：每日 10:00
    步骤：
      1. 拿所有 ready_to_publish 的 listing
      2. 对每个 listing 调用 /api/v1/publish/start
      3. 等待 30 秒（mock 适配器即时返回）
      4. 检查状态：failed > 0 → 告警
    """
    log.info("=" * 60)
    log.info("[Workflow 2] 自动发布")
    log.info("=" * 60)

    try:
        listings = await api("/api/v1/listings?status=ready_to_publish&limit=50")
        log.info(f"找到 {len(listings)} 个待发布 listing")

        if not listings:
            await send_alert("info", "今日无待发布", "没有 ready_to_publish 状态的 listing")
            return {"status": "no_listings"}

        succeeded, failed = 0, 0
        for l in listings:
            try:
                result = await api(
                    "/api/v1/publish/start",
                    method="POST",
                    json={"listing_id": l["id"], "auto_execute": True},
                )
                # 等 30 秒让 worker 处理
                await asyncio.sleep(2)

                job = await api(f"/api/v1/publish/jobs/{result['job_id']}")
                if job.get("platform_status") == "published":
                    succeeded += 1
                    log.info(f"  ✓ 发布成功: {l['title'][:30]}")
                else:
                    failed += 1
                    log.warning(f"  ✗ 发布失败: {l['title'][:30]} - {job.get('last_error', '')}")
            except Exception as e:
                failed += 1
                log.exception(f"  ✗ 发布异常: {l['title'][:30]}")

        log.info(f"发布完成: 成功 {succeeded}, 失败 {failed}")

        if failed > 0:
            await send_alert(
                "warning",
                "发布任务失败",
                f"今日 {failed} 个 listing 发布失败（成功 {succeeded}）",
            )
        else:
            await send_alert(
                "info",
                "发布完成",
                f"全部 {succeeded} 个 listing 成功发布",
            )

        return {"status": "ok", "succeeded": succeeded, "failed": failed}

    except Exception as e:
        log.exception("发布失败")
        await send_alert("error", "发布异常", str(e))
        return {"status": "exception", "error": str(e)}


# ============ 工作流 5: 周报生成（V2.0）============
async def weekly_report_workflow():
    """每周一 08:00 生成上周 7 天校准报告

    V2.0：调 /api/v1/drift/weekly-report
    """
    log.info("=" * 60)
    log.info("[Workflow 5] V2.0 周报生成")
    log.info("=" * 60)

    try:
        result = await api(
            "/api/v1/drift/weekly-report",
            method="POST",
        )
        log.info(f"  ✓ 周报已生成：drift_id={result.get('id')}, 样本={result.get('sample_size')}")
        return {"status": "ok", "drift_id": result.get("id"), "sample_size": result.get("sample_size")}
    except Exception as e:
        log.exception("周报生成失败")
        await send_alert("error", "周报生成异常", str(e))
        return {"status": "exception", "error": str(e)}


# ============ 工作流 4: 销量反馈采集（V2.0）============
async def feedback_workflow():
    """每日 02:00 拉取昨天销量（T+1）

    V2.0：调用 /api/v1/sales-feedback/collect?day=昨天
    """
    log.info("=" * 60)
    log.info("[Workflow 4] 销量反馈采集 (V2.0)")
    log.info("=" * 60)

    try:
        from datetime import timedelta
        beijing = timezone(timedelta(hours=8))
        yesterday = (datetime.now(beijing) - timedelta(days=1)).date().isoformat()
        result = await api(
            f"/api/v1/sales-feedback/collect",
            method="POST",
            params={"day": yesterday},
        )
        log.info(f"  ✓ 拉取 {yesterday} 销量：{result.get('inserted', 0)} 条")
        return {"status": "ok", "day": yesterday, "inserted": result.get("inserted", 0)}

    except Exception as e:
        log.exception("反馈采集失败")
        await send_alert("error", "反馈采集异常", str(e))
        return {"status": "exception", "error": str(e)}


# ============ 工作流 3: 监控告警 ============
async def monitor_alerts_workflow():
    """每 10 分钟检查告警

    步骤：
      1. 拿最近告警
      2. 找 error 级
      3. 如有 → 通知（email / webhook / 钉钉等）
    """
    log.info("=" * 60)
    log.info("[Workflow 3] 监控告警")
    log.info("=" * 60)

    try:
        alerts = await api("/api/v1/alerts?limit=20")
        errors = [a for a in alerts if a.get("level") == "error"]

        log.info(f"最近告警: {len(alerts)} 条，错误: {len(errors)} 条")

        if errors:
            # 这里可扩展为发送邮件/钉钉/webhook
            # MVP 仅记录 + 触发后端告警（避免循环）
            for e in errors[:5]:
                log.warning(f"  ⚠ {e['title']}: {e.get('message', '')}")
        else:
            log.info("✓ 无错误级告警")

        return {"status": "ok", "errors": len(errors)}

    except Exception as e:
        log.exception("监控失败")
        return {"status": "exception", "error": str(e)}


# ============ 调度器 ============
async def scheduler_loop():
    """简单的 cron 调度器

    模拟 n8n 的定时触发 + 条件分支
    """
    log.info("=" * 60)
    log.info("Temu Workflow Orchestrator 启动")
    log.info(f"API: {API_BASE}")
    log.info("=" * 60)

    last_run = {"import": None, "publish": None, "monitor": None, "feedback": None, "weekly_report": None}

    while True:
        # 北京时间 = UTC + 8h
        beijing_tz = timezone(timedelta(hours=8))
        now = datetime.now(beijing_tz)
        hour = now.hour
        minute = now.minute
        # Monday = 0
        weekday = now.weekday()

        # 06:00 → 每日导入
        if hour == 6 and last_run["import"] != now.date():
            log.info(f"[{now}] 触发: 每日导入")
            await daily_import_workflow()
            last_run["import"] = now.date()

        # 02:00 → V2.0 销量反馈（T+1）
        if hour == 2 and last_run["feedback"] != now.date():
            log.info(f"[{now}] 触发: V2.0 销量反馈采集")
            await feedback_workflow()
            last_run["feedback"] = now.date()

        # 周一 08:00 → V2.0 周报
        if weekday == 0 and hour == 8 and last_run["weekly_report"] != now.date():
            log.info(f"[{now}] 触发: V2.0 周报生成")
            await weekly_report_workflow()
            last_run["weekly_report"] = now.date()

        # 10:00 → 自动发布
        if hour == 10 and last_run["publish"] != now.date():
            log.info(f"[{now}] 触发: 自动发布")
            await auto_publish_workflow()
            last_run["publish"] = now.date()

        # 每 10 分钟 → 监控告警
        if minute % 10 == 0 and last_run["monitor"] != now.strftime("%Y-%m-%d %H:%M"):
            log.info(f"[{now}] 触发: 监控告警")
            await monitor_alerts_workflow()
            last_run["monitor"] = now.strftime("%Y-%m-%d %H:%M")

        await asyncio.sleep(30)  # 每 30 秒检查一次


# ============ CLI 入口 ============
async def run_once(workflow_name: str):
    """单次运行某个工作流"""
    workflows = {
        "import": daily_import_workflow,
        "publish": auto_publish_workflow,
        "monitor": monitor_alerts_workflow,
        "feedback": feedback_workflow,
        "weekly_report": weekly_report_workflow,
    }
    if workflow_name not in workflows:
        log.error(f"未知工作流: {workflow_name}，可选: {list(workflows)}")
        return
    await workflows[workflow_name]()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # CLI: python scripts/orchestrator.py import
        asyncio.run(run_once(sys.argv[1]))
    else:
        # 默认：进入调度循环
        asyncio.run(scheduler_loop())