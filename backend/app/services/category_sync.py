"""类目字典增量同步 — V1.1-A2

PRD §19 V1.1：类目/属性字典自动增量同步
实现：
  - 周期任务：每日从 Temu 适配器拉取最新字典
  - diff：新字典 vs 当前激活字典 → 找出新增/修改/删除
  - 自动激活（如有变更）或人工确认（首次）
  - 字典版本号管理（避免完全覆盖）
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class CategoryDictDiff:
    added: list[dict]      # 新增类目
    modified: list[dict]    # 修改类目
    removed: list[str]      # 删除的类目 ID


def diff_dicts(old: list[dict], new: list[dict]) -> CategoryDictDiff:
    """对比新旧字典，返回 diff

    Args:
        old: 旧字典 [{category_id, name, parent_id, ...}]
        new: 新字典 [{category_id, name, parent_id, ...}]
    """
    old_map = {c["category_id"]: c for c in old}
    new_map = {c["category_id"]: c for c in new}

    added = [c for cid, c in new_map.items() if cid not in old_map]
    removed = [cid for cid in old_map if cid not in new_map]

    modified = []
    for cid, new_c in new_map.items():
        if cid in old_map:
            old_c = old_map[cid]
            # 关键字段比对（name/parent_id/attributes）
            if old_c.get("name") != new_c.get("name") or \
               old_c.get("parent_id") != new_c.get("parent_id"):
                modified.append({
                    "category_id": cid,
                    "before": old_c,
                    "after": new_c,
                })

    return CategoryDictDiff(added=added, modified=modified, removed=removed)


def generate_version_label(site: str, fetched_at: datetime) -> str:
    """生成字典版本号"""
    return f"{site}-{fetched_at.strftime('%Y%m%d%H%M%S')}"


def should_auto_activate(diff: CategoryDictDiff, threshold: int = 10) -> bool:
    """是否应自动激活新字典

    PRD §20 R-13 类目字典陈旧：字典导入时立即激活
    但变更过多时建议人工确认（防止平台规则大幅变更冲击业务）
    """
    total_changes = len(diff.added) + len(diff.modified) + len(diff.removed)
    return total_changes <= threshold