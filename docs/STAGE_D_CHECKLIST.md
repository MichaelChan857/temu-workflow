# D 阶段就绪检查 — 切真实 Temu 环境

> 触发条件：客户提供 5 项凭据
> 当前状态：**mock 模式已就绪，等待切换**

## 需要的 5 项凭据

| # | 凭据 | 来源 | 用途 |
|---|---|---|---|
| 1 | `TEMU_APP_KEY` | Temu Partner Platform → 应用详情 | API 调用身份 |
| 2 | `TEMU_APP_SECRET` | 同上 | 签名计算 |
| 3 | `TEMU_ACCESS_TOKEN` | Temu Partner Platform → 卖家授权 | 调用授权 |
| 4 | `TEMU_SANDBOX_BASE` (可选) | Temu 技术支持 | 沙箱测试 |
| 5 | `SHOP_ID` + `TARGET_SITE` | 卖家后台 | 标识提交到哪个店铺 |

## 切换步骤（执行清单）

### D.1 —修改 .env

```bash
# 容器内
docker compose exec backend bash

cat > /app/.env <<EOF
SECRET_KEY=<生产级 32+ 字节随机>
DATABASE_URL=postgresql+asyncpg://temu:<pwd>@postgres:5432/temu_workflow
TEMU_USE_MOCK=false
TEMU_APP_KEY=<客户提供的 KEY>
TEMU_APP_SECRET=<客户提供的 SECRET>
TEMU_ACCESS_TOKEN=<客户提供的 TOKEN>
TEMU_RUN_MODE=sandbox  # 或 live
TEMU_SANDBOX_BASE=https://open-sandbox.temu.com/api
ANTHROPIC_API_KEY=<可选>
EOF
```

### D.2 —重启服务

```bash
docker compose restart temu-adapter backend
```

### D.3 —验证适配器

```bash
# 健康检查
curl http://localhost:8001/health
# 期望：{"status": "ok", "mode": "sandbox", ...}

# 测试签名
curl -X POST http://localhost:8001/v1/products/publish \
  -H "Content-Type: application/json" \
  -d '{"idempotency_key":"test-real-001","shop_id":"<SHOP_ID>","listing_snapshot":{"title":"Test"}}'
```

### D.4 —验证签名算法

真实 Temu 签名可能在 V1/V2/V3 之间，**第一步先确认**：

```python
# backend/scripts/test_temu_signature.py
import hmac, hashlib, time, uuid
# 按 Partner Platform 文档调整 sign_request() 实现
```

### D.5 —端到端联调

1. 导入示例 CSV → 5 候选入选
2. 一审通过 1 个
3. AI 生成 → 人工编辑 → 二审通过
4. 发起发布 → 等待平台返回
5. 在 Temu 卖家后台核实商品是否上架
6. 截图归档

### D.6 —监控上线

```bash
# 加入告警接收人配置
docker compose exec backend python -c "
import asyncio
from app.db.session import init_db, AsyncSessionLocal
from app.db.models import ConfigVersion

async def f():
    await init_db()
    async with AsyncSessionLocal() as db:
        cfg = ConfigVersion(
            config_type='alert_config',
            version='v1',
            definition={'email': 'ops@example.com', 'webhook': ''},
            is_active=True,
        )
        db.add(cfg)
        await db.commit()

asyncio.run(f())
"
```

## 切换后立即监控的指标

| 指标 | 阈值 | 动作 |
|---|---|---|
| `temu_adapter_errors_total` | 5 分钟内 > 5 | 检查签名/凭据 |
| `publish_failed_total` 突增 | 5 分钟内 > 3 | 暂停 + 排查 |
| 平台返回 401/403 | 任何 | **立即停发布 + 重新授权** |
| 幂等键重复率 | > 10% | 检查前端防重逻辑 |

## 回滚方案

如真实环境出现严重问题：

```bash
# 1. 切回 mock
sed -i 's/TEMU_USE_MOCK=false/TEMU_USE_MOCK=true/' .env
docker compose restart temu-adapter backend

# 2. 暂停所有 PENDING job
docker compose exec backend python scripts/pause_all_jobs.py

# 3. 复盘
docker compose logs --tail=200 backend > incident.log
```

## D 阶段交付物清单

- [ ] .env 生产配置
- [ ] 真实 Temu 签名验证（脚本）
- [ ] 真实环境 1 个商品上架
- [ ] 截图归档
- [ ] 监控告警配置
- [ ] 客户签字验收（PRD §22 DoD）