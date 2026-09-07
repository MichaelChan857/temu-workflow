# 运维 Runbook

> 适用于运维 / 实施方
> 版本：V1.0 | 日期：2026-09-02

## 目录

- [1. 常见告警解读](#1-常见告警解读)
- [2. 故障排查流程](#2-故障排查流程)
- [3. 紧急操作 SOP](#3-紧急操作-sop)
- [4. 监控指标阈值](#4-监控指标阈值)
- [5. 回滚方案](#5-回滚方案)

## 1. 常见告警解读

### 1.1 "Temu 候选不足"

- **含义**：今日推荐 < 20 个
- **影响**：业务可接受，但需关注长期
- **处置**：
  1. 登录告警中心查看详情
  2. 检查数据源是否稳定（导入文件/接口）
  3. 检查规则是否过严（`/scoring-config` 调整）
  4. 联系客户补充候选数据

### 1.2 "Temu 授权过期"

- **含义**：`TEMU_ACCESS_TOKEN` 失效
- **影响**：发布全部失败
- **处置**（**最高优先级**）：
  1. 立即停止所有发布按钮
  2. 登录 Temu Partner Platform 重新授权
  3. 更新 `.env` 中 `TEMU_ACCESS_TOKEN`
  4. `docker compose restart temu-adapter backend`
  5. 手动重试失败的 job

### 1.3 "API 错误率超阈值"

- **含义**：Temu 接口 5xx 比例 > 5%
- **影响**：发布延迟
- **处置**：
  1. 登录 `/alerts` 查看详细错误
  2. 检查 Temu 服务状态页
  3. 等待 5 分钟自动重试
  4. 持续 > 30 分钟 → 联系 Temu 技术支持

### 1.4 "队列积压"

- **含义**：待处理任务 > 100
- **影响**：处理延迟
- **处置**：
  1. `docker compose logs backend` 查看 worker 日志
  2. `docker compose restart backend` 重启 worker
  3. 如有死锁，手动清理 stuck 任务

### 1.5 "重试耗尽"

- **含义**：某 job 3 次重试仍失败
- **影响**：单个商品发布失败
- **处置**：
  1. 登录 `/publish/jobs/{id}` 查看错误详情
  2. 根据 `error_class` 处置：
     - `retryable` → 等 10 分钟后手动重试
     - `fatal` → 字段错误，退回 listing 编辑
     - `need_auth` → 重新授权后重试
     - `need_fix` → 修改字段后重试
  3. 或调用 `POST /publish/jobs/{id}/close` 人工关闭

## 2. 故障排查流程

### 2.1 前端打不开

```
浏览器控制台 (F12) → Network → 看失败请求
  ↓
API 返回 5xx → 见 2.2
API 返回 401 → Token 过期，重新登录
API 返回 403 → 权限不足，检查角色
CORS 错误 → 检查 CORS_ORIGINS 配置
```

### 2.2 后端无响应

```bash
# 1. 看进程
docker compose ps

# 2. 看日志
docker compose logs --tail=100 backend

# 3. 常见错误
# - "could not connect to server" → 数据库挂了
# - "address already in use" → 端口冲突
# - "ModuleNotFoundError" → 镜像损坏，重新构建
```

### 2.3 发布全部失败

```bash
# 1. 检查适配器健康
curl http://localhost:8001/health

# 2. 看适配器日志
docker compose logs --tail=50 temu-adapter

# 3. 模拟测试
curl -X POST http://localhost:8001/v1/products/publish \
  -H "Content-Type: application/json" \
  -d '{"idempotency_key":"test","shop_id":"s1","listing_snapshot":{},"candidate_title":"test"}'

# 4. 看告警
curl http://localhost:8000/api/v1/alerts
```

### 2.4 评分异常

```bash
# 1. 检查激活的评分配置
curl http://localhost:8000/api/v1/scoring-config/active

# 2. 检查规则是否误改
curl http://localhost:8000/api/v1/scoring-config

# 3. 回滚到上一版本
# 前端 /scoring-config → 选历史版本 → 激活
```

## 3. 紧急操作 SOP

### 3.1 停止所有发布

```bash
# 暂停所有 PENDING job
docker compose exec backend python -c "
import asyncio
from sqlalchemy import update
from app.db.session import AsyncSessionLocal
from app.db.models import PublishJob, PublishStatus

async def f():
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(PublishJob)
            .where(PublishJob.status == PublishStatus.PENDING)
            .values(status=PublishStatus.FAILED, last_error='emergency stop')
        )
        await db.commit()
        print('all pending jobs stopped')
asyncio.run(f())
"
```

### 3.2 重启单个服务

```bash
docker compose restart backend
docker compose restart temu-adapter
docker compose restart frontend
```

### 3.3 完全重启

```bash
docker compose down
docker compose up -d
```

### 3.4 重置数据库（**危险：会丢失数据**）

```bash
docker compose down -v  # 删除数据卷
docker compose up -d
docker compose exec backend python scripts/seed_users.py
```

## 4. 监控指标阈值

### 4.1 Prometheus 集成（推荐）

`backend/app/main.py` 增加 `/metrics` 端点暴露：

```python
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)
```

### 4.2 推荐监控项

| 指标 | 类型 | 阈值 |
|---|---|---|
| `http_requests_total` | Counter | - |
| `http_request_duration_seconds` | Histogram | P95 < 3s |
| `publish_jobs_pending` | Gauge | < 100 |
| `publish_jobs_failed_total` | Counter | 增速 < 10/小时 |
| `temu_adapter_errors_total` | Counter | 增速 < 5/分钟 |
| `db_pool_overflow` | Gauge | < 5 |

## 5. 回滚方案

### 5.1 代码回滚

```bash
# 查看最近版本
git log --oneline -20

# 回滚到指定 commit
git checkout <commit-sha>
docker compose up -d --build

# 或使用镜像 tag
docker compose pull temu-backend:v1.0.0
```

### 5.2 数据回滚（严重情况）

```bash
# 1. 备份当前数据
./backup.sh

# 2. 停止服务
docker compose down

# 3. 恢复备份
gunzip -c /var/backups/temu/temu_YYYYMMDD_HHMMSS.sql.gz | \
  docker compose up -d postgres  # 启动数据库

# 4. 验证数据
docker compose exec postgres psql -U temu -d temu_workflow -c "SELECT COUNT(*) FROM candidate_products;"

# 5. 启动全栈
docker compose up -d
```

### 5.3 配置回滚（评分/字典）

前端 `/scoring-config` 或 `/categories` → 选历史版本 → 激活。

## 6. 联系信息

- 实施方：{{IMPLEMENTATION_ORG}}
- 实施方负责人：{{IMPLEMENTATION_OWNER}}
- 电话：{{IMPLEMENTATION_PHONE}}
- 邮箱：{{IMPLEMENTATION_EMAIL}}
- Temu 技术支持：https://partner.temu.com/support