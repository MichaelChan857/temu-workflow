# 客户演示脚本 — 5 分钟看完 Temu Workflow

> 演示人：实施方
> 客户：Temu 卖家业务方
> 目标：让客户看到完整业务流的"看、点、用"

## 演示前准备（5 分钟）

```bash
# 1. 启动后端服务
cd C:\Users\Administrator\Desktop\temu-workflow\backend
uv run --with aiosqlite --with pydantic-settings --with fastapi --with sqlalchemy --with pyjwt --with httpx --with openpyxl --with uvicorn --with python-multipart --with loguru python scripts/run_dev.py

# 2. 另开窗口 — 创建测试用户（首次）
uv run --with aiosqlite --with pydantic-settings --with fastapi --with sqlalchemy --with pyjwt --with httpx --with openpyxl --with uvicorn --with python-multipart --with loguru python scripts/seed_users.py

# 3. 浏览器打开
# http://127.0.0.1:8000/ui/login.html
```

## 演示流程（按这个顺序点）

### 第 1 步：登录（30 秒）
1. 打开 `http://127.0.0.1:8000/ui/login.html`
2. 看登录页设计（玻璃拟态 + 6 角色卡片）
3. 点"**张运营**"卡片（自动登录为 operator 角色）
4. 提示："这个页面对所有用户统一，6 角色快捷登录方便演示"

### 第 2 步：业务看板（45 秒）
1. 自动跳转到 `dashboard.html`
2. 介绍 5 大指标卡：批次 / 候选 / 待一审 / 待发布 / 失败
3. 重点看**转化漏斗图**：从导入 → 一审 → 资料 → 二审 → 发布 6 步
4. "我们这个漏斗图能直接看出**今天卡在哪一步**"

### 第 3 步：CSV导入（30 秒）
1. 切到 terminal 跑：
```bash
cd backend
uv run --with httpx python scripts/orchestrator.py import
```
2. 看输出："导入 10 个候选 → 5 个高分推荐"
3. **刷新业务看板**（浏览器按 F5）→ 看到数字实时更新
4. "这就是您的运营每天的工作：早上 6 点跑一次导入"

### 第 4 步：一审工作台（60 秒）⭐ 重点
1. 切到一审工作台
2. 看候选卡片网格：图片 +分数 + 标题 + 价格
3. 点一个高分候选 → **弹出详情**
4. 演示 6 维评分条（热度 / 竞争 / 利润 / 趋势 / 评价 / 风险）
5. "AI 评过分了，但**人来做最后决定**——这是'人机协同'"
6. 点"通过"按钮 → 卡片消失
7. 点"驳回" → 填原因 → 确认

### 第 5 步：资料生成（45 秒）
1. 刚通过的候选会自动出现"AI 生成中"状态
2. （如果是后台运行）点 `/listings/[id]` 看 AI 生成的标题/卖点/描述
3. "AI 不会编造材质、规格、认证（PRD 强约束）"
4. 演示**版本对比**：修改标题 → 显示新版本

### 第 6 步：二审（60 秒）⭐ 关键合规
1. 进入二审页 `second-review/[id]`
2. 看顶部**校验结果**：必填错误 / 警告（需确认）
3. **强制同人校验**："您配置的是 suggested，允许同人但记录事件；如果您要强制不同人，在系统配置改"
4. 通过 → **快照冻结**（listing 状态变 ready_to_publish）

### 第 7 步：发布监控（30 秒）
1. 切到发布监控 `publish.html`
2. 看任务列表（状态徽章 + 一键全部发布按钮）
3. "操作员一键发布全部 → 后台异步调用 Temu → 幂等键防重复"

### 第 8 步：告警中心（30 秒）
1. 切到告警 `alerts.html`
2. "n8n 工作流发现异常 → 自动发到这里"
3. 点"发送测试告警" → 看实时刷新
4. "生产环境可对接邮件 / 飞书 / 钉钉 webhook"

### 第 9 步：系统配置（30 秒）
1. 切到 `config.html`
2. 演示**评分模型可视化配置**：
   - 拖动"热度"滑块从 25% → 30%
   - 总和自动校验，必须 = 100%
3. "运营可以自己调整权重，**不需要发版**"
4. 演示**类目字典同步**：粘贴 JSON → diff 预览 → 应用
5. "V1.1 V2.0 V2.0 的规划都基于这套配置"

### 第 10 步：编排器后台运行（30 秒）⭐
1. 切到 terminal：
```bash
# 进入调度循环（每天自动跑 3 个工作流）
uv run python scripts/orchestrator.py
```
2. "这是我们的'无 n8n'方案：3 个 Python 脚本，0 依赖、可读、易调试"
3. "如果您更偏好 n8n UI，docs/STAGE_D_CHECKLIST.md 有切真实 Temu 的步骤"

## 演示中常被问到的问题

### Q1：数据真实性？
答："这是 mock 模式，数据真实跑通；真实 Temu 联调需要 5 项凭据（见 STAGE_D_CHECKLIST.md），你们提供后我们 3 天可切真实"

### Q2：AI 文案如何收费？
答："我们用 Claude Sonnet 4.5 按 token 计费；每个 listing 约 1000 token（约 ¥0.02）；mock 模式不计费"

### Q3：并发量？
答："单店铺 500 候选 < 10 分钟（PRD §15.1 上限），单决策 P95 < 1.5s（test_nonfunctional 实测）"

### Q4：多店铺？
答："MVP 单店铺；V1.1 多店铺（schema 已支持 shop_id）。如果你们上线就有多店铺需求，建议优先做 V1.1"

### Q5：审核人员怎么知道有新批次？
答："告警中心会有 'first_review_ready' 通知；可对接邮件/飞书/钉钉"

### Q6：图片侵权怎么检测？
答："MVP 有 `BRAND_INFRINGE` 规则（lv/nike/gucci 等品牌词检测）；V1.2 可接入阿里云/腾讯云图片鉴黄鉴政服务"

## 演示完后的下一步

1. **客户提供凭据** → 我们切真实环境 → 上线
2. **运营试用** → 用 mock 数据跑 1 周 → 反馈
3. **小批量生产** → 选 10 个真实商品 → 全流程 → 验证
4. **PRD §22 DoD 客户签字** → 正式上线

## 关键演示文档

- `README.md`：项目总览
- `docs/DEPLOY.md`：部署指南
- `docs/RUNBOOK.md`：运维手册
- `docs/USER_MANUAL.md`：用户操作手册
- `docs/V2_PLAN.md`：V2.0 业务闭环计划
- `docs/STAGE_D_CHECKLIST.md`：切真实环境 SOP

## 联系方式

- 实施方负责人：[客户填]
- 邮箱：[客户填]
- 工作时间：周一至周五 9:00-18:00
- 紧急联系：[客户填]