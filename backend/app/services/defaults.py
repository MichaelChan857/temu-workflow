"""PRD §21 待确认事项的保守默认值 — W8-D7

13 项待确认事项 + 我方建议默认值 + 客户可改标记

未填写但已签 = 按默认值实施（PRD 确认书 §5）
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DefaultDecision:
    code: str
    question: str
    default_value: str
    rationale: str  # 为什么选这个默认值
    configurable_via: str  # 客户怎么改


DEFAULTS = [
    DefaultDecision(
        code="D-01",
        question="首期 Temu 店铺、站点、商家模式和目标语言",
        default_value="US / 全托管 / en",
        rationale="US 站点流量最大；全托管模式适合初期；英文覆盖 80% 目标用户",
        configurable_via=".env: TEMU_SITE / TEMU_MERCHANT_MODE / TARGET_LANGUAGE",
    ),
    DefaultDecision(
        code="D-02",
        question="候选商品具体来源、每日预计数量、字段样例及素材授权责任",
        default_value="CSV 文件 / 500 个/日 / 客户自有商品库",
        rationale="MVP 阶段 CSV 最快；客户自有数据授权最清晰",
        configurable_via="data_sources 表配置 + 上传文件",
    ),
    DefaultDecision(
        code="D-03",
        question="每日任务时间、时区和推荐目标数是否固定为 20",
        default_value="每日 06:00 (UTC+8) / 20 个",
        rationale="凌晨运行不影响业务；20 个符合 MVP 默认",
        configurable_via="n8n workflow + config_versions.thresholds.target_count",
    ),
    DefaultDecision(
        code="D-04",
        question="首期允许/禁止类目、价格区间、重量尺寸和利润底线",
        default_value="USD 5-200 / ≤2kg / 长+宽+高 ≤90cm / 毛利 ≥25%",
        rationale="匹配 Temu 主流品类；物流边界符合一般小包；毛利底线覆盖运营成本",
        configurable_via="config_versions.thresholds + rules.py 硬性规则",
    ),
    DefaultDecision(
        code="D-05",
        question="初始评分维度、权重、最低推荐分和类目占比限制",
        default_value="6 维（热25/竞20/利20/趋20/评10/险5）/ 75 分 / 40%",
        rationale="PRD §8.3 默认权重；75 分中等偏严；40% 类目占比防过度集中",
        configurable_via="/scoring-config 页面可视化调整",
    ),
    DefaultDecision(
        code="D-06",
        question="一审、二审人员及是否强制不同人审批",
        default_value="建议模式（同人允许但事件标记）",
        rationale="PRD L19 推荐；不阻塞业务但保留审计；客户可改 forced",
        configurable_via="config_versions (type=review_policy)",
    ),
    DefaultDecision(
        code="D-07",
        question="标题、描述、图片、SKU、价格和初始化数量的业务口径",
        default_value="标题 ≤200 字符 / 描述 3-5 句 / 价格含币种 / SKU 全局唯一 / 初始数量 = 100",
        rationale="符合 Temu 商品接口约束；初始数量 100 留补充空间",
        configurable_via="规则引擎 + 二审校验",
    ),
    DefaultDecision(
        code="D-08",
        question="对 AI 内容的品牌、功效、认证和敏感词限制",
        default_value="禁止编造规格/材质/功效/认证/品牌授权；13 个敏感词黑名单",
        rationale="PRD §8.4 + FR-051 强制约束；事实白名单已实现",
        configurable_via="claude_client.py SENSITIVE_WORDS",
    ),
    DefaultDecision(
        code="D-09",
        question="Temu 应用申请、接口权限和测试店铺由哪一方负责、完成时间",
        default_value="客户方负责申请 + 提供测试店铺；我方负责联调",
        rationale="申请需客户主体资质；联调是技术工作",
        configurable_via="待客户回复具体时间表",
    ),
    DefaultDecision(
        code="D-10",
        question="API 失败重试次数、告警接收人和人工处理 SLA",
        default_value="3 次重试（指数退避 1-60s）/ 邮件告警 / SLA 2 小时",
        rationale="PRD FR-089；邮件最通用；2 小时匹配一般运营节奏",
        configurable_via=".env: PUBLISH_MAX_ATTEMPTS + 告警 webhook 配置",
    ),
    DefaultDecision(
        code="D-11",
        question="日志保存期、数据导出范围和用户权限清单",
        default_value="业务+审计 2 年 / 接口+AI 180 天 / 系统 90 天",
        rationale="PRD §12.1 强制要求",
        configurable_via="audit.RETENTION_DAYS + 导出 API",
    ),
    DefaultDecision(
        code="D-12",
        question="MVP 验收使用测试环境还是小批量生产商品",
        default_value="客户提供测试店铺 + 沙箱环境（若有）；否则小批量 5-10 个生产商品",
        rationale="测试店铺最安全；若无则小批量 + 撤回方案",
        configurable_via="客户回复具体环境",
    ),
    DefaultDecision(
        code="D-13",
        question="客户对接窗口负责人与紧急联系方式",
        default_value="{{CUSTOMER_OWNER}}（{{CUSTOMER_ORG}}）/ {{IMPLEMENTATION_OWNER}}（{{IMPLEMENTATION_ORG}}）",
        rationale="PRD 文档占位；待客户填写",
        configurable_via="客户邮件回复",
    ),
]


def get_all_defaults() -> list[DefaultDecision]:
    return DEFAULTS


def get_decision(code: str) -> Optional[DefaultDecision]:
    for d in DEFAULTS:
        if d.code == code:
            return d
    return None


def unresolved() -> list[DefaultDecision]:
    """未通过客户确认的（占位或未填）"""
    return [d for d in DEFAULTS if "{{" in d.default_value]


def resolved_with_default() -> list[DefaultDecision]:
    """我方提供默认值（客户可改）"""
    return [d for d in DEFAULTS if "{{" not in d.default_value]