# V2.0 业务闭环 — 设计计划

> PRD §19 V2.0 业务闭环
> 状态：设计阶段（待客户授权销量数据）
> 触发条件：客户后续授权

## 一、目标

引入**销量反馈信号**自动校准评分模型——把"我猜哪个能爆"变成"卖得好的验证过"。

## 二、核心能力

### 2.1 销量反馈接入

| 数据源 | 接入方式 | 频率 |
|---|---|---|
| Temu 订单 API | 每日拉取（按 platform_product_id 关联） | T+1 |
| Temu 流量/曝光 API | 同上 | T+1 |
| 客户回传（线下补发） | CSV 上传 | 按需 |

### 2.2 反馈到评分

每个发布商品 → 30 天观察窗口 → 累积：
- 实际订单量
- 退款率
- 评分变化
- 类目内排名

→ 计算 **sales_realized_score**（实现分）
→ 与 AI **predicted_score** 比对 → 计算 **calibration_error**
→ 用 calibration_error 反向调整权重

### 2.3 模型自学习

- **不允许**自动重训（PRD §6.5 "AI 的主观判断不得替代可计算的结构化指标"）
- 仅做**偏差监控 + 人工调权建议**
- 每周生成"模型校准报告"——运营可一键应用 / 忽略 / 微调

### 2.4 相似商品聚类

- 用 image embedding + text embedding
- 检测重复图片 / 重复标题 → 阻断重复发布（PRD FR-021）
- 同聚类内共享评分参考

## 三、技术架构

```
[Temu Order API] ─┐
                  ├─→ feedback_collector.py ─→ [sales_records 表]
[CSV Upload]   ───┘                              │
                                                 ▼
                        calibration_engine.py ─→ [model_drift 表]
                                                 │
                                                 ▼
                        weekly_report.py ─→ [运营审核] ─→ [评分配置激活]
```

## 四、数据模型

```sql
sales_records (
  id, listing_id, platform_product_id,
  date, order_count, refund_count,
  rating, category_rank,
  created_at
)

model_drift (
  id, model_version, evaluated_at,
  predicted_score_avg, realized_score_avg,
  calibration_error, dimension_errors_json,
  recommended_weight_adjustments_json
)
```

## 五、关键决策

| 决策 | 原因 |
|---|---|
| **不自训练模型** | PRD §6.5 / §8.4：AI 主观判断不得替代结构化指标；只做偏差报告 |
| **30 天窗口** | Temu 新品流量周期约 2-4 周；30 天足够评估 |
| **校准报告人工应用** | 避免模型漂移失控；运营可拒绝调整 |
| **聚类只用于去重** | 不用于评分（避免"同类商品一刀切"） |

## 六、依赖项

- Temu 订单 API 访问权限（需要客户额外申请）
- 反馈数据保存 1 年
- 校准报告 UI（V2.0 前端）

## 七、风险与缓解

| 风险 | 缓解 |
|---|---|
| 销量数据噪声大（季节性 / 平台推广） | 30 天窗口 + 同期类目均值对比 |
| 反馈数据被篡改 | 双签名（订单 API 校验 + 客户回传对比） |
| 模型漂移失控 | 人工审核报告；不允许自动激活 |

## 八、里程碑

| 阶段 | 周期 | 交付 |
|---|---|---|
| 反馈接入 | 2 周 | feedback_collector + sales_records 表 |
| 校准引擎 | 3 周 | calibration_engine + model_drift 表 + 周报 |
| 聚类去重 | 2 周 | image embedding + 重复检测 |
| 联调验收 | 1 周 | 端到端 + 客户签字 |

## 九、当前状态

✅ V1.1 完成（HTTP API 连接器 + 字典同步 + 批量操作）  
✅ 评分模型可手动调权（/scoring-config）  
⏳ V2.0 需客户授权 + 订单 API 凭据 + 校准 UI

**当前实现已经支持 V2.0 的一半工作：模型权重可配置、版本可回滚、校准数据可追溯**。待客户授权销量数据后即可增量开发。
