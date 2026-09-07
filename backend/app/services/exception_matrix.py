"""异常处理矩阵 — PRD §11 13 类异常

每类异常：
  - 触发条件
  - 系统处理
  - 是否自动重试
  - 人工动作

提供统一的异常分类 + 重试判定 + 告警。
"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ExceptionCategory(str, Enum):
    """异常分类（PRD FR-087 / L24）"""
    RETRYABLE = "retryable"      # 网络/超时/限流 → 自动重试
    FATAL = "fatal"              # 参数错误 → 不重试
    NEED_AUTH = "need_auth"      # 授权过期 → 需重新授权
    NEED_FIX = "need_fix"        # 业务字段错误 → 退回编辑
    PROCESSING_FAILED = "processing_failed"  # 系统级失败（OCR/AI）
    DATA_QUALITY = "data_quality"  # 数据质量问题


@dataclass
class ExceptionRule:
    code: str                      # 唯一代码
    category: ExceptionCategory
    retry: bool
    description: str
    user_action: str               # 用户/运营的处置
    auto_action: str               # 系统自动处置


# ============ 13 类异常（PRD §11）============
EXCEPTION_MATRIX: dict[str, ExceptionRule] = {

    # 1. 文件格式或字段错误（PRD §11）
    "FILE_FORMAT_ERROR": ExceptionRule(
        code="FILE_FORMAT_ERROR",
        category=ExceptionCategory.FATAL,
        retry=False,
        description="CSV/XLSX 文件格式或必填字段缺失",
        user_action="修正模板后重新导入；查看错误行号和原因",
        auto_action="拒绝错误行，输出行号和原因；正确行按配置继续",
    ),

    # 2. 数据源不可用
    "DATA_SOURCE_UNAVAILABLE": ExceptionRule(
        code="DATA_SOURCE_UNAVAILABLE",
        category=ExceptionCategory.RETRYABLE,
        retry=True,
        description="外部数据源接口超时或 5xx",
        user_action="检查数据源健康状态",
        auto_action="指数退避重试；批次标记部分失败/失败并告警",
    ),

    # 3. 候选不足
    "INSUFFICIENT_CANDIDATES": ExceptionRule(
        code="INSUFFICIENT_CANDIDATES",
        category=ExceptionCategory.DATA_QUALITY,
        retry=False,
        description="合格候选少于目标数（如 < 20）",
        user_action="补充候选数据或接受不足",
        auto_action="按实际数量输出推荐并告警；不为凑数降低硬性合规标准",
    ),

    # 4. AI 超时/限流
    "AI_TIMEOUT_RATE_LIMIT": ExceptionRule(
        code="AI_TIMEOUT_RATE_LIMIT",
        category=ExceptionCategory.RETRYABLE,
        retry=True,
        description="Claude API 超时或触发限流",
        user_action="超限后人工重跑",
        auto_action="任务入重试队列，保留输入；有限次数重试",
    ),

    # 5. AI 输出格式错误
    "AI_FORMAT_ERROR": ExceptionRule(
        code="AI_FORMAT_ERROR",
        category=ExceptionCategory.RETRYABLE,
        retry=True,
        description="AI 返回非结构化 / 编造事实字段",
        user_action="确认规则源信息完整后人工介入",
        auto_action="结构化修复或重新请求；有限次数重试；失败转人工",
    ),

    # 6. 类目无匹配
    "NO_CATEGORY_MATCH": ExceptionRule(
        code="NO_CATEGORY_MATCH",
        category=ExceptionCategory.FATAL,
        retry=False,
        description="Temu 类目匹配分低于阈值",
        user_action="人工选择类目后才能进入二审",
        auto_action="标记待人工选类目；不允许二审通过",
    ),

    # 7. 必填属性缺失
    "MISSING_REQUIRED_ATTR": ExceptionRule(
        code="MISSING_REQUIRED_ATTR",
        category=ExceptionCategory.FATAL,
        retry=False,
        description="二审前必填属性缺失",
        user_action="补充字段",
        auto_action="阻止提交二审或二审通过；定位具体字段",
    ),

    # 8. 图片失效/不合规
    "IMAGE_INVALID": ExceptionRule(
        code="IMAGE_INVALID",
        category=ExceptionCategory.NEED_FIX,
        retry=True,
        description="图片 URL 失效或尺寸/格式不合规",
        user_action="替换图片",
        auto_action="标记错误并阻止发布；可重新拉取一次",
    ),

    # 9. 店铺授权过期
    "SHOP_AUTH_EXPIRED": ExceptionRule(
        code="SHOP_AUTH_EXPIRED",
        category=ExceptionCategory.NEED_AUTH,
        retry=False,
        description="Temu Partner Platform Token 过期",
        user_action="重新登录 Partner Platform 获取新 Token",
        auto_action="停止发布，归类为需授权；告警通知管理员",
    ),

    # 10. API 限流/5xx/网络超时
    "API_RATE_LIMIT_5XX": ExceptionRule(
        code="API_RATE_LIMIT_5XX",
        category=ExceptionCategory.RETRYABLE,
        retry=True,
        description="Temu API 429 / 5xx / 网络超时",
        user_action="超上限后检查 API 状态",
        auto_action="延迟重试，保持同一幂等键",
    ),

    # 11. API 业务校验失败
    "API_BUSINESS_ERROR": ExceptionRule(
        code="API_BUSINESS_ERROR",
        category=ExceptionCategory.NEED_FIX,
        retry=False,
        description="Temu 返回 400 业务错误",
        user_action="修订字段后重新二审",
        auto_action="记录字段级错误并退回编辑",
    ),

    # 12. 请求超时且结果未知
    "API_TIMEOUT_UNKNOWN": ExceptionRule(
        code="API_TIMEOUT_UNKNOWN",
        category=ExceptionCategory.RETRYABLE,
        retry=True,
        description="请求超时，无法确认 Temu 是否已创建商品",
        user_action="无法确认时人工核对",
        auto_action="先用查询接口/幂等键核实；不直接创建新请求",
    ),

    # 13. 重复发布
    "DUPLICATE_PUBLISH": ExceptionRule(
        code="DUPLICATE_PUBLISH",
        category=ExceptionCategory.FATAL,
        retry=False,
        description="同店铺已有相同 SKU / 来源商品",
        user_action="确认复用或管理员解除阻断",
        auto_action="阻止请求；展示已存在平台商品 ID",
    ),

    # 14.（额外）平台异步审核失败
    "PLATFORM_ASYNC_REVIEW_FAILED": ExceptionRule(
        code="PLATFORM_ASYNC_REVIEW_FAILED",
        category=ExceptionCategory.NEED_FIX,
        retry=False,
        description="Temu 异步审核最终失败",
        user_action="修订/申诉在平台侧处理",
        auto_action="更新失败原因，转退回编辑或关闭",
    ),
}


class RetryPolicy:
    """PRD §11.1 重试规则"""
    MAX_AUTO_RETRIES = 3
    BASE_DELAY_SEC = 1.0
    MAX_DELAY_SEC = 60.0


def should_auto_retry(code: str, attempt: int) -> bool:
    """是否应该自动重试

    仅以下场景自动重试：
    - 类别 = retryable
    - attempt < 3
    """
    rule = EXCEPTION_MATRIX.get(code)
    if not rule:
        return False
    if not rule.retry:
        return False
    if attempt >= RetryPolicy.MAX_AUTO_RETRIES:
        return False
    return True


def get_rule(code: str) -> Optional[ExceptionRule]:
    return EXCEPTION_MATRIX.get(code)


def list_retryable_codes() -> list[str]:
    """所有自动重试的异常代码"""
    return [c for c, r in EXCEPTION_MATRIX.items() if r.retry]


def list_by_category(category: ExceptionCategory) -> list[ExceptionRule]:
    return [r for r in EXCEPTION_MATRIX.values() if r.category == category]