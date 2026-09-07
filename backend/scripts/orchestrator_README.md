"""n8n 编排器使用说明（替代 n8n UI）

由于网络限制无法装 n8n，我们用纯 Python 实现了相同功能的编排器。
"""

# ===================== 启动方式 =====================

## 单次执行（手动触发）

```bash
# 跑一次"每日导入"工作流
uv run python scripts/orchestrator.py import

# 跑一次"自动发布"工作流
uv run python scripts/orchestrator.py publish

# 跑一次"监控告警"工作流
uv run python scripts/orchestrator.py monitor
```

## 持续运行（调度模式）

```bash
# 进入调度循环（每天自动跑）
uv run python scripts/orchestrator.py
```

调度时间表（北京时间）：

| 时间 | 工作流 | 说明 |
|---|---|---|
| 06:00 | `daily_import` | 每日导入 CSV |
| 10:00 | `auto_publish` | 自动发布 ready_to_publish |
| 每 10 分钟 | `monitor_alerts` | 检查错误级告警 |

## 替换为 n8n 时的步骤（网络好时）

如果未来能装上 n8n，可以这样替换：

1. n8n UI → Workflows → Import → 选择 `n8n/workflows/temu-selection-daily.json`
2. 配置环境变量：API 地址、Token
3. 启动工作流

现有 n8n 工作流 JSON 已经写好（`n8n/workflows/temu-selection-daily.json`），**功能等价**。

## 编排器 vs n8n 对比

| 特性 | n8n | 编排器（orchestrator.py） |
|---|---|---|
| 可视化编排 | ✅ | ❌ 代码 |
| 触发器 | ✅ Cron/Webhook | ✅ Cron（asyncio） |
| HTTP 节点 | ✅ | ✅ httpx |
| 条件分支 | ✅ | ✅ Python |
| 错误重试 | ✅ | ✅ try/except |
| 告警 | ✅ Email/Slack | ✅ 后端 /alerts |
| 接入容易度 | 需安装 | 0 依赖 |
| 实时监控 | ✅ UI | ❌ 仅日志 |

## 当前运行状态（用 orchestrator.py 验证）

```bash
# 1. 跑每日导入
uv run python scripts/orchestrator.py import
# 输出：[OK] 导入完成 batch=xxx 推荐 5 个...

# 2. 跑发布
uv run python scripts/orchestrator.py publish
# 输出：[OK] 全部 N 个 listing 成功发布

# 3. 跑监控
uv run python scripts/orchestrator.py monitor
# 输出：[OK] 无错误级告警
```