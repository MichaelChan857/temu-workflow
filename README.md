# Temu 自动选品与上品工作流

> MVP 实施 — 路径 4（Scrappy MVP + 关键借力）
> 周期：8 周 / 80 人天

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 工作流编排 | **n8n** | 低代码、业务方可拖拽；批量发布性能可扩 |
| 业务后端 | **FastAPI + Python 3.12** | 异步、与 n8n HTTP 集成顺；SQLAlchemy 2.0 |
| 数据库 | **PostgreSQL 15** | 事务、JSONB、唯一约束支持完整 |
| 缓存/队列 | **Redis 7** | 幂等键、锁、Celery broker |
| 前端 | **Next.js 14 (App Router)** | 一审/二审/看板 |
| Temu 适配器 | **FastAPI 独立微服务** | 隔离变化，签名/限流/异步接收器 |
| AI 文案 | **Claude API** | 仅 1 个用途：标题/描述生成 |
| 容器化 | **Docker Compose** | 一键起环境 |

## 快速开始

```bash
# 1. 启动所有服务
docker compose up -d

# 2. 数据库迁移
docker compose exec backend alembic upgrade head

# 3. 导入示例候选商品
docker compose exec backend python scripts/import_sample.py

# 4. 打开 n8n 触发工作流
open http://localhost:5678

# 5. 查看一审页面
open http://localhost:3000
```

## 目录结构

```
temu-workflow/
├── backend/          # FastAPI 主服务 + Temu 适配器
│   ├── app/
│   │   ├── api/      # 路由
│   │   ├── core/     # 配置/安全
│   │   ├── db/       # 模型/会话
│   │   ├── services/ # 业务逻辑
│   │   └── schemas/  # Pydantic
│   └── scripts/
├── frontend/         # Next.js 一审/二审
├── db/migrations/    # Alembic
├── docs/             # 设计文档 + 客户确认包
└── docker-compose.yml
```

## 进度

### W1 D1 — MVP 脚手架（已完成）
- [x] 项目骨架
- [x] docker-compose 技术栈
- [x] 数据库 DDL（12 张核心表）
- [x] Temu 适配器骨架
- [x] CSV 导入 + 评分 + 推荐 端到端跑通
- [x] 一审列表页

### W2 — 认证 + 权限 + 并发（已完成）
- [x] JWT 登录 + 6 角色 RBAC
- [x] 一审乐观锁（version + CAS）
- [x] n8n 工作流 JSON（CSV→评分→告警→通知）
- [x] 前端登录页 + token 持久化 + 权限按钮
- [x] 发布 API 占位（含幂等键生成）
- [x] 端到端联调脚本（无需启动 n8n UI）

### W3 — 多格式 + 配置化 + 告警 UI（已完成）
- [x] XLSX 导入器（CSV/XLSX 共用标准化/去重/评分）
- [x] 数据源连接器抽象（CSV/XLSX/API/ThirdParty）
- [x] data_sources 表驱动 + CRUD API + 健康检查
- [x] 评分配置可视化（运营可改权重/阈值，版本化）
- [x] 告警中心前端（轮询 + 手动测试告警）
- [x] XLSX E2E 测试（生成→解析→规则→评分）

### W4 — AI 文案 + 资料编辑 + 类目字典（已完成）
- [x] Claude API 客户端（mock + 真实双模式）
- [x] 标题/卖点/描述生成 + 事实白名单 + 敏感词校验
- [x] 失败重试（3次） + 转人工
- [x] listing 资料编辑 API（PUT + version+1）
- [x] 版本对比（diff 字段）+ 回退（已冻结不可）
- [x] listing_versions 表（每次编辑/AI 生成/回退留痕）
- [x] 类目字典导入（CSV/JSON）+ 搜索
- [x] 前端资料编辑页 + 版本历史面板
- [x] AI 文案 E2E 测试（5 项断言）

### W5 — Temu 适配器 + 幂等发布 + 重试（已完成）
- [x] Temu 签名框架（HMAC-SHA256，可切换 sandbox/live）
- [x] 4 类错误分类（retryable / fatal / need_auth / need_fix）
- [x] 指数退避 + 抖动（最多 3 次）
- [x] 幂等键生成（每店铺+每发布意图唯一）
- [x] 异步受理 → 轮询（最多 10 次 × 2 秒）→ 终态
- [x] 10 个适配器端点（publish/query/category/media/classify/admin）
- [x] X-Simulate-Error 头注入（测试用）
- [x] 发布 Worker（asyncio 后台 + 手动 retry/close）
- [x] 真实场景测试：5 场景通过（happy/rate_limit/auth/validation/platform_review）

### W6 — 二审 + 快照 + 同人校验（已完成）
- [x] 二审决策 API（approve/return/reject）
- [x] 校验规则（必填/标题长度/重复标题/图片URL）
- [x] 警告确认（attributes 缺失不阻塞但需 confirm_warnings）
- [x] 快照冻结（publish_snapshot + snapshot_version）
- [x] 冻结后 3 端点拒绝编辑（edit/rollback/second_review）
- [x] 同人校验（forced 拒绝 / suggested 允许+事件标记）
- [x] 前端二审页（校验结果可视化 + 三按钮）
- [x] 状态机串联：editing → second_review → ready_to_publish → publish
- [x] 发布页（start + 轮询 + retry）

### W7 — 收官：验收 + 文档 + 安全（已完成）
- [x] PRD §17.2 端到端 15 条验收用例 — 15/15 通过
- [x] 部署文档（环境/变量/迁移/备份恢复/上线清单）
- [x] 运维 Runbook（5 类常见告警 + 故障排查 + 紧急 SOP + 回滚）
- [x] 用户操作手册（6 角色 + 状态机 + FAQ + 已知限制）
- [x] 安全验证（凭证脱敏 + JWT过期 + 幂等唯一 + 备份脚本 + 敏感词）
- [x] 备份恢复演练脚本（pg_dump/gzip + restore.sh）

### W8 — 基于客户文档的精细化（已完成）
- [x] 完整状态机（19 状态 + 7 硬终态 + 1 准终态 + 36 迁移规则）
- [x] 14 类异常处理矩阵（4 大分类 + 重试规则）
- [x] 7 类日志审计 + 10 种脱敏模式 + 留存期检查
- [x] 40 权限点矩阵（PRD §13.1 完整对齐）
- [x] 非功能需求自动化校验（性能/可观测性/易用性）
- [x] 14 风险点代码化（含 7 高风险 + 监控指标）
- [x] §21 待确认默认值（13 项 + 12 项提供默认）
- [x] 集成测试套件（13 个子测试，全部通过）

### V1.1 — 效率与稳定性（已完成）
- [x] HTTP API 连接器（4 类认证 + 4 类分页 + 字段映射）
- [x] 内部商品库 / 1688 预设
- [x] 类目字典增量同步（diff + 自动激活阈值）
- [x] 批量编辑 listing（≤100 个/批）
- [x] 批量二审（≤50 个/批，approve/reject）
- [x] 集成上游选品工具（temu-product-sourcing schema 转换）
- [x] V2.0 业务闭环设计文档（销量反馈 + 校准）
- [x] D 阶段就绪检查清单（真实环境切换 SOP）

## 文档

- 部署：[docs/DEPLOY.md](docs/DEPLOY.md)
- 运维：[docs/RUNBOOK.md](docs/RUNBOOK.md)
- 用户手册：[docs/USER_MANUAL.md](docs/USER_MANUAL.md)

## 启动

```bash
# 1. 启动所有服务
docker compose up -d

# 2. 创建 6 个测试用户
docker compose exec backend python scripts/seed_users.py

# 3. 导入示例候选商品
docker compose exec backend python scripts/import_sample.py

# 4. 端到端联调（验证登录/导入/并发决策/RBAC）
docker compose exec backend python scripts/test_e2e.py

# 4b. XLSX 端到端测试（无需数据库）
docker compose exec backend python scripts/test_xlsx_e2e.py

# 5. 打开
#   http://localhost:3000     ← 一审工作台（自动跳登录页）
#   http://localhost:8000/docs ← API 文档
#   http://localhost:5678     ← n8n 工作流 UI
#   http://localhost:8001/docs ← Temu 适配器
```

## 测试账号（默认密码 admin123）

| 账号 | 角色 | 权限 |
|---|---|---|
| admin | 系统管理员 | 全部 |
| operator | 选品运营 | 批次/一审/查看审计 |
| editor | 商品编辑 | 查看/资料编辑/一审 |
| reviewer | 上品审核员 | 一审+二审 |
| publisher | 发布操作员 | 发起发布/重试 |
| readonly | 只读验收 | 仅查看 |

## 文档

- [需求文档 V1.0](../Temu自动选品与上品工作流需求文档.docx)
- [业务确认书 V1.0](../Temu自动选品与上品工作流-业务逻辑确认文档.docx)
- [客户邮件包](../temu_customer_pack/)

## License

Internal use only.