"""日志审计 — PRD §12

7 类日志 + 留存期 + 脱敏
"""
import re
import hashlib
from enum import Enum
from typing import Optional


class LogType(str, Enum):
    BUSINESS = "business"            # 业务状态日志
    REVIEW = "review"                # 审核日志
    API = "api"                      # 接口日志
    AI = "ai"                        # AI 调用日志
    AUDIT = "audit"                  # 操作审计日志
    SYSTEM = "system"                # 系统运行日志
    SECURITY = "security"            # 安全日志（新增）


# 留存期（PRD §12.1）
RETENTION_DAYS = {
    LogType.BUSINESS: 730,    # ≥2 年
    LogType.REVIEW: 730,      # ≥2 年
    LogType.API: 180,         # ≥180 天
    LogType.AI: 180,          # ≥180 天
    LogType.AUDIT: 730,       # ≥2 年
    LogType.SYSTEM: 90,       # ≥90 天
    LogType.SECURITY: 365,    # 安全日志保留 1 年
}


# ============ 脱敏规则 ============
SENSITIVE_PATTERNS = [
    # 凭证类
    (re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*[\'"]?([^\s\'"]+)'), r'\1=[REDACTED]'),
    (re.compile(r'(?i)(api[_-]?key|access[_-]?key|app[_-]?key)\s*[=:]\s*[\'"]?([^\s\'",]+)'), r'\1=[REDACTED]'),
    (re.compile(r'(?i)(token|secret)\s*[=:]\s*[\'"]?([^\s\'",]+)'), r'\1=[REDACTED]'),
    # Bearer JWT
    (re.compile(r'(?i)Bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+'), 'Bearer [REDACTED]'),
    # API Key 前缀
    (re.compile(r'sk-[A-Za-z0-9\-]{20,}'), '[REDACTED_OPENAI_KEY]'),
    (re.compile(r'pplx-[A-Za-z0-9\-]{20,}'), '[REDACTED_PERPLEXITY_KEY]'),
    # 签名/HMAC
    (re.compile(r'(?i)(signature|hmac|sig)\s*[=:]\s*[A-Fa-f0-9]{16,}'), r'\1=[REDACTED]'),
    # 手机号（中国大陆）
    (re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)'), '[REDACTED_PHONE]'),
    # 身份证
    (re.compile(r'\d{17}[\dXx]'), '[REDACTED_ID_CARD]'),
    # 邮箱
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), '[REDACTED_EMAIL]'),
    # 银行卡（13-19 位数字）
    (re.compile(r'(?<!\d)\d{13,19}(?!\d)'), '[REDACTED_CARD]'),
]


def scrub(text: str) -> str:
    """脱敏文本中的敏感信息"""
    if not text:
        return text
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def scrub_dict(d: dict) -> dict:
    """递归脱敏 dict（key 和 value 都脱敏）"""
    out = {}
    for k, v in d.items():
        safe_key = scrub(str(k))
        k_lower = k.lower()
        # 含敏感 key → 整个 value 当作密码处理
        sensitive_keys = ("password", "passwd", "pwd", "secret", "token", "api_key", "access_key", "app_key", "tokens")
        is_sensitive_key = k_lower in sensitive_keys or any(k_lower.endswith(s) for s in ("_password", "_token", "_secret", "_key"))

        if isinstance(v, str):
            if is_sensitive_key:
                out[safe_key] = "[REDACTED]"
            else:
                out[safe_key] = scrub(v)
        elif isinstance(v, dict):
            out[safe_key] = scrub_dict(v)
        elif isinstance(v, list):
            out[safe_key] = [
                "[REDACTED]" if isinstance(x, str) and is_sensitive_key
                else scrub(x) if isinstance(x, str)
                else scrub_dict(x) if isinstance(x, dict)
                else x
                for x in v
            ]
        else:
            out[safe_key] = v
    return out


# ============ 字段级审计（PRD §12.2）============
def field_audit(before: dict, after: dict) -> dict:
    """字段级变更前后值（PRD §12.2）

    Returns:
        {"changed_fields": [...], "changes": [{field, before, after}]}
    """
    changed = []
    all_keys = set(before.keys()) | set(after.keys())
    for k in all_keys:
        if before.get(k) != after.get(k):
            changed.append({
                "field": k,
                "before": scrub(str(before.get(k, ""))),
                "after": scrub(str(after.get(k, ""))),
            })
    return {
        "changed_fields": [c["field"] for c in changed],
        "changes": changed,
    }


# ============ 写入接口 ============
def make_log(
    log_type: LogType,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor_id: Optional[str] = None,
    actor_name: Optional[str] = None,
    reason: Optional[str] = None,
    payload: Optional[dict] = None,
    trace_id: Optional[str] = None,
) -> dict:
    """构造一条日志（PRD §12.2 全部要求字段）"""
    import time
    return {
        "log_type": log_type.value,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": event_type,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "reason": scrub(reason or ""),
        "payload": scrub_dict(payload or {}),
        "trace_id": trace_id,
        "created_at": int(time.time() * 1000),  # ms
        "retention_days": RETENTION_DAYS[log_type],
    }


# ============ 留存期检查 ============
def check_retention(log_type: LogType, log_age_days: int) -> bool:
    """检查日志是否超过留存期"""
    return log_age_days < RETENTION_DAYS[log_type]


def should_prune(log_type: LogType, log_age_days: int) -> bool:
    """是否应清理"""
    return log_age_days >= RETENTION_DAYS[log_type]