"""14 风险点代码化缓解 — PRD §20

每项风险 → 代码级检查/缓解/告警
"""
from enum import Enum
from dataclasses import dataclass


class RiskSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class RiskMitigation:
    code: str
    risk: str
    probability: RiskSeverity
    impact: str
    mitigation: str  # 代码级动作
    monitor: str      # 监控指标


# ============ PRD §20 的 14 项风险 ============
RISKS = [

    # 1. Temu API 权限或版本变化
    RiskMitigation(
        code="R-01",
        risk="Temu API 权限或版本变化",
        probability=RiskSeverity.HIGH,
        impact="无法联调或字段改动",
        mitigation="适配器隔离层（adapters/temu_server.py）+ 字段映射配置化；client 用枚举错误处理",
        monitor="temu_adapter_errors_total 增速",
    ),

    # 2. 不同站点/商家模式差异
    RiskMitigation(
        code="R-02",
        risk="不同站点/商家模式差异",
        probability=RiskSeverity.HIGH,
        impact="需求和工期扩大",
        mitigation="通用商品模型 + 站点映射；MVP 锁定单站点 + 商家模式",
        monitor="per_site_error_rate",
    ),

    # 3. 候选数据来源不稳定或不合规
    RiskMitigation(
        code="R-03",
        risk="候选数据来源不稳定或不合规",
        probability=RiskSeverity.HIGH,
        impact="无法持续选品 / 合规风险",
        mitigation="data_sources 记录 owner + authorization_note；禁止未授权爬虫；导入时校验",
        monitor="data_source_health",
    ),

    # 4. 数据质量不足
    RiskMitigation(
        code="R-04",
        risk="数据质量不足",
        probability=RiskSeverity.HIGH,
        impact="评分失真 / 资料缺失",
        mitigation="模板校验 + 必填缺失直接淘汰 + 数据缺失打 '待补充' 不猜均值",
        monitor="data_gaps_per_listing",
    ),

    # 5. AI 幻觉
    RiskMitigation(
        code="R-05",
        risk="AI 幻觉",
        probability=RiskSeverity.HIGH,
        impact="商品事实错误 → 平台驳回",
        mitigation="事实白名单校验（suspicious 词必须 source 含）+ 两次人工审核 + 结构化输出",
        monitor="ai_validation_failures_total",
    ),

    # 6. 评分模型无历史验证
    RiskMitigation(
        code="R-06",
        risk="评分模型无历史验证",
        probability=RiskSeverity.HIGH,
        impact="推荐质量不稳定",
        mitigation="评分模型配置化（config_versions）+ 阈值可调 + 不宣称 '爆款预测'",
        monitor="approval_rate / score_distribution",
    ),

    # 7. 类目/属性匹配错误
    RiskMitigation(
        code="R-07",
        risk="类目/属性匹配错误",
        probability=RiskSeverity.MEDIUM,
        impact="错类目发布 / API 失败",
        mitigation="置信度阈值 + 低于阈值必须人工选类目 + 类目变化重校验属性",
        monitor="category_match_score_distribution",
    ),

    # 8. 图片/文字侵权
    RiskMitigation(
        code="R-08",
        risk="图片/文字侵权",
        probability=RiskSeverity.HIGH,
        impact="商品下架 / 店铺风险",
        mitigation="素材 rights_confirmed 必填 + 敏感词规则 + 品牌词规则 + 人工审核",
        monitor="rights_unconfirmed_count",
    ),

    # 9. API 超时导致重复商品
    RiskMitigation(
        code="R-09",
        risk="API 超时导致重复商品",
        probability=RiskSeverity.MEDIUM,
        impact="重复上架",
        mitigation="幂等键（SHA256(shop_id|snapshot_version|listing_id)）+ 超时先查询 + 不直接重发",
        monitor="duplicate_publish_attempts",
    ),

    # 10. 平台审核异步或规则不透明
    RiskMitigation(
        code="R-10",
        risk="平台审核异步或规则不透明",
        probability=RiskSeverity.MEDIUM,
        impact="提交成功但最终失败",
        mitigation="区分 '已提交' / '平台审核中' / '已发布'；轮询 + 回调；保留原始原因",
        monitor="platform_review_duration_p95",
    ),

    # 11. 审核人员批量误操作
    RiskMitigation(
        code="R-11",
        risk="审核人员批量误操作",
        probability=RiskSeverity.MEDIUM,
        impact="错误发布",
        mitigation="高风险操作二次确认 + 权限隔离 + 冻结快照 + 完整审计",
        monitor="high_risk_action_rate",
    ),

    # 12. 接口限流和 AI 成本
    RiskMitigation(
        code="R-12",
        risk="接口限流和 AI 成本",
        probability=RiskSeverity.MEDIUM,
        impact="批次延迟 / 成本超支",
        mitigation="队列限速 + 缓存 + 预算告警 + 分级模型（规则 vs LLM）",
        monitor="ai_cost_per_batch",
    ),

    # 13. 类目字典同步延迟
    RiskMitigation(
        code="R-13",
        risk="类目字典陈旧",
        probability=RiskSeverity.MEDIUM,
        impact="类目匹配失败",
        mitigation="config_versions 字典版本化 + 字典导入时立即激活 + 告警 30 天未更新",
        monitor="category_dict_age_days",
    ),

    # 14. 凭据泄露
    RiskMitigation(
        code="R-14",
        risk="Temu Token / Claude Key 泄露",
        probability=RiskSeverity.MEDIUM,
        impact="未授权访问 / 资金损失",
        mitigation="加密存储（KMS）+ 定期轮换 + 日志脱敏 + IP 白名单",
        monitor="suspicious_access_attempts",
    ),
]


def get_risk(code: str) -> RiskMitigation | None:
    for r in RISKS:
        if r.code == code:
            return r
    return None


def by_probability(sev: RiskSeverity) -> list[RiskMitigation]:
    return [r for r in RISKS if r.probability == sev]


def all_codes() -> list[str]:
    return [r.code for r in RISKS]