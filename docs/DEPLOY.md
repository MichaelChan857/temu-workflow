# 部署文档

> 适用于运维 / DBA / 实施方
> 版本：V1.0 | 日期：2026-09-02

## 1. 环境要求

| 组件 | 版本 | 备注 |
|---|---|---|
| Docker | 24+ | 含 Docker Compose V2 |
| PostgreSQL | 15 | 推荐 16 也可 |
| Redis | 7 | 可选（队列/MVP 用 asyncio） |
| 内存 | ≥ 4 GB | n8n + 后端 + 前端 + DB |
| 磁盘 | ≥ 20 GB | 数据卷 |

## 2. 快速部署

```bash
# 1. 克隆代码
git clone <repo-url> temu-workflow
cd temu-workflow

# 2. 修改环境变量
cp .env.example .env  # 不存在则手动创建
# 编辑 .env：设置 SECRET_KEY、TEMU_APP_KEY、TEMU_APP_SECRET、ANTHROPIC_API_KEY

# 3. 启动
docker compose up -d

# 4. 数据库初始化（自动建表）
docker compose exec backend python -c "from app.db.session import init_db; asyncio.run(init_db())"

# 5. 创建种子用户
docker compose exec backend python scripts/seed_users.py

# 6. 导入示例数据（可选）
docker compose exec backend python scripts/import_sample.py

# 7. 健康检查
curl http://localhost:8000/
curl http://localhost:8001/health
curl http://localhost:5678/healthz
curl http://localhost:3000/
```

## 3. 环境变量清单

| 变量 | 必填 | 默认 | 说明 |
|---|:---:|---|---|
| `SECRET_KEY` | ✅ | `change-me-...` | JWT 签名密钥，**生产环境必须 ≥32 字节随机** |
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://...` | PostgreSQL 连接串 |
| `REDIS_URL` | ⬜ | `redis://redis:6379/0` | Redis 连接串 |
| `TEMU_API_BASE` | ✅ | `http://temu-adapter:8001` | Temu 适配器地址 |
| `TEMU_USE_MOCK` | ✅ | `true` | 是否 mock 模式；生产改 `false` |
| `TEMU_APP_KEY` | ⬜ | mock | Temu Partner Platform 应用 Key |
| `TEMU_APP_SECRET` | ⬜ | mock | Temu 应用 Secret |
| `TEMU_ACCESS_TOKEN` | ⬜ | mock | Temu 卖家访问 Token |
| `ANTHROPIC_API_KEY` | ⬜ | - | Claude API Key（AI 文案） |
| `CORS_ORIGINS` | ✅ | `http://localhost:3000,...` | 允许的跨域来源，逗号分隔 |

## 4. 数据库迁移

MVP 阶段使用 `Base.metadata.create_all()` 自动建表。生产环境建议：

```bash
# 1. 生成迁移
docker compose exec backend alembic revision --autogenerate -m "init"

# 2. 应用迁移
docker compose exec backend alembic upgrade head

# 3. 回滚
docker compose exec backend alembic downgrade -1
```

## 5. 备份与恢复（PRD §15.2）

### 5.1 备份策略

- **每日全量备份**：`pg_dump`
- **保留期**：30 天
- **目标**：RPO ≤ 24 小时，RTO ≤ 4 小时

### 5.2 备份脚本

```bash
#!/bin/bash
# backup.sh — 每日全量备份
BACKUP_DIR=/var/backups/temu
DATE=$(date +%Y%m%d_%H%M%S)
FILG = ${BACKUP_DIR}/temu_${DATE}.sql.gz

mkdir -p ${BACKUP_DIR}
docker compose exec -T postgres pg_dump -U temu temu_workflow | gzip > ${FILG}

# 清理 30 天前
find ${BACKUP_DIR} -name "temu_*.sql.gz" -mtime +30 -delete

echo "[$(date)] backup complete: ${FILG}"
```

### 5.3 恢复脚本

```bash
#!/bin/bash
# restore.sh <backup-file>
FILG = $1
if [ -z "${FILG}" ]; then
  echo "Usage: $0 <backup-file>"
  exit 1
fi

# 1. 停止写入
docker compose exec backend python -c "
from app.db.session import engine
import asyncio
async def f():
    await engine.dispose()
asyncio.run(f())
"

# 2. 恢复
gunzip -c ${FILG} | docker compose exec -T postgres psql -U temu -d temu_workflow

# 3. 验证
docker compose exec backend python -c "
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models import CandidateProduct
import asyncio
async def f():
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(CandidateProduct).limit(1))
        print('restore ok:', r.scalar_one_or_none())
asyncio.run(f())
"
```

### 5.4 演练

```bash
# 模拟恢复演练（不破坏生产）
docker compose exec postgres pg_dump -U temu temu_workflow > /tmp/temu_test.sql
docker compose exec postgres psql -U temu -d temu_workflow_test < /tmp/temu_test.sql
```

## 6. 监控

### 6.1 健康检查端点

| 服务 | 端点 |
|---|---|
| Backend | `GET /` → `{"app": "Temu Workflow MVP"}` |
| Temu Adapter | `GET /health` → `{"status": "ok", "mode": "mock"}` |
| n8n | `GET /healthz` |
| Frontend | `GET /` → 200 |
| PostgreSQL | `pg_isready` |

### 6.2 关键指标

| 指标 | 阈值 |
|---|---|
| 队列积压 | > 100 条告警 |
| API 错误率 | > 5% 告警 |
| 接口 P95 延迟 | > 3s 告警 |
| 授权过期 | 立即告警 |
| 重试耗尽 | 立即告警 |

## 7. 服务端口

| 端口 | 服务 | 公网？ |
|---|---|---|
| 3000 | 前端 | 仅内网或反代 |
| 5432 | PostgreSQL | 仅内网 |
| 5678 | n8n | 仅内网 |
| 6379 | Redis | 仅内网 |
| 8000 | 后端 API | 反代 + HTTPS |
| 8001 | Temu 适配器 | 仅内网 |

## 8. 上线检查清单

- [ ] `SECRET_KEY` 替换为 32+ 字节随机值
- [ ] `TEMU_USE_MOCK=false`
- [ ] `TEMU_APP_KEY/SECRET/TOKEN` 从 Temu Partner Platform 获取
- [ ] `ANTHROPIC_API_KEY` 从 Anthropic Console 获取
- [ ] CORS 限定具体域名
- [ ] 备份脚本加入 crontab
- [ ] 监控 + 告警接入（推荐：Prometheus + Alertmanager）
- [ ] 防火墙：仅暴露 3000 + 8000（反代）
- [ ] 数据库启用 SSL
- [ ] 应用日志结构化输出
- [ ] 备份恢复演练通过

## 9. 故障应急

参见 `RUNBOOK.md`。