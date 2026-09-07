"""完整状态机 — PRD §6.1 14 个状态 + 8 个终态

所有合法迁移规则集中定义；任何非法迁移都会被校验拒绝。
"""
from enum import Enum


class ListingStatus(str, Enum):
    IMPORTED = "imported"
    NORMALIZED = "normalized"
    FILTERED_OUT = "filtered_out"
    SCORED = "scored"
    FIRST_REVIEW = "first_review"
    CONTENT_GENERATING = "content_generating"
    EDITING = "editing"
    SECOND_REVIEW = "second_review"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHING = "publishing"
    PLATFORM_REVIEWING = "platform_reviewing"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"
    NOT_SELECTED = "not_selected"
    REJECTED_1 = "rejected_1"
    REJECTED_2 = "rejected_2"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"
    CLOSED = "closed"


# PRD §6.1：8 个终态
TERMINAL_STATUSES = {
    ListingStatus.FILTERED_OUT,
    ListingStatus.NOT_SELECTED,
    ListingStatus.REJECTED_1,
    ListingStatus.REJECTED_2,
    ListingStatus.ARCHIVED,
    ListingStatus.CANCELLED,
    ListingStatus.CLOSED,
}

# 准终态：仅可去 archived
QUASI_TERMINAL = {ListingStatus.PUBLISHED}


# ============ 迁移规则 ============
TRANSITIONS = {
    ListingStatus.IMPORTED: [
        (ListingStatus.NORMALIZED, "normalize", {"deduped"}),
        (ListingStatus.FILTERED_OUT, "hard_rule_reject", {"hard_rule_hit"}),
        (ListingStatus.IMPORTED, "first_review_return", {"reason_code"}),
    ],
    ListingStatus.NORMALIZED: [
        (ListingStatus.SCORED, "scored", {"score"}),
        (ListingStatus.NOT_SELECTED, "scored_below_threshold", {}),
        (ListingStatus.FILTERED_OUT, "hard_rule_reject", {"hard_rule_hit"}),
    ],
    ListingStatus.SCORED: [
        (ListingStatus.FIRST_REVIEW, "selected_for_review", {"in_top_n"}),
        (ListingStatus.NOT_SELECTED, "below_quota", {"category_quota_full"}),
        (ListingStatus.IMPORTED, "first_review_return", {"reason_code"}),
    ],
    ListingStatus.FIRST_REVIEW: [
        (ListingStatus.CONTENT_GENERATING, "first_review_approve", {"actor"}),
        (ListingStatus.REJECTED_1, "first_review_reject", {"reason_code"}),
        (ListingStatus.IMPORTED, "first_review_return", {"reason_code"}),
    ],
    ListingStatus.CONTENT_GENERATING: [
        (ListingStatus.EDITING, "ai_generated", {"ai_success"}),
        (ListingStatus.EDITING, "ai_failed_transfer_to_human", {}),
        (ListingStatus.REJECTED_1, "ai_cancelled", {"reason_code"}),
    ],
    ListingStatus.EDITING: [
        (ListingStatus.SECOND_REVIEW, "submit_for_second_review", {"all_required_filled"}),
        (ListingStatus.REJECTED_2, "second_review_reject", {"reason_code"}),
        (ListingStatus.EDITING, "second_review_return", {"reason_code"}),
        (ListingStatus.EDITING, "human_edit", {}),
    ],
    ListingStatus.SECOND_REVIEW: [
        (ListingStatus.READY_TO_PUBLISH, "second_review_approved", {"snapshot_frozen"}),
        (ListingStatus.EDITING, "second_review_return", {"reason_code"}),
        (ListingStatus.REJECTED_2, "second_review_reject", {"reason_code"}),
    ],
    ListingStatus.READY_TO_PUBLISH: [
        (ListingStatus.PUBLISHING, "publish_started", {"snapshot_match"}),
        (ListingStatus.EDITING, "reopen_edit", {"admin_override"}),
    ],
    ListingStatus.PUBLISHING: [
        (ListingStatus.PUBLISHED, "publish_sync_success", {"platform_product_id"}),
        (ListingStatus.PLATFORM_REVIEWING, "publish_async_accepted", {"platform_task_id"}),
        (ListingStatus.PUBLISH_FAILED, "publish_failed", {"error_class"}),
    ],
    ListingStatus.PLATFORM_REVIEWING: [
        (ListingStatus.PUBLISHED, "platform_poll_published", {"poll_terminal"}),
        (ListingStatus.PUBLISH_FAILED, "platform_poll_failed", {"poll_terminal"}),
    ],
    ListingStatus.PUBLISH_FAILED: [
        (ListingStatus.PUBLISHING, "manual_retry", {"retry_within_limit"}),
        (ListingStatus.CLOSED, "manual_close", {"reason_code"}),
    ],
    ListingStatus.PUBLISHED: [
        (ListingStatus.ARCHIVED, "archive_after_days", {"days"}),
    ],
    # 终态不再迁移
    ListingStatus.FILTERED_OUT: [],
    ListingStatus.NOT_SELECTED: [],
    ListingStatus.REJECTED_1: [],
    ListingStatus.REJECTED_2: [],
    ListingStatus.ARCHIVED: [],
    ListingStatus.CANCELLED: [],
    ListingStatus.CLOSED: [],
}


class IllegalTransition(Exception):
    def __init__(self, from_status: str, to_status: str, reason: str = ""):
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(f"illegal transition {from_status} → {to_status}: {reason}")


def can_transition(from_status: str, to_status: str) -> bool:
    if from_status == to_status:
        return True
    try:
        f = ListingStatus(from_status)
    except ValueError:
        return False
    if f in TERMINAL_STATUSES:
        return False
    if f in QUASI_TERMINAL and to_status != ListingStatus.ARCHIVED.value:
        return False
    allowed = TRANSITIONS.get(f, [])
    return any(t.value == to_status for t, _, _ in allowed)


def assert_transition(from_status: str, to_status: str, **conditions) -> None:
    f = ListingStatus(from_status)
    if f in TERMINAL_STATUSES:
        raise IllegalTransition(from_status, to_status, "from terminal status")
    if f in QUASI_TERMINAL and to_status != ListingStatus.ARCHIVED.value:
        raise IllegalTransition(from_status, to_status, "from quasi-terminal (only archived)")

    transitions = TRANSITIONS.get(f, [])
    matched = [t for t, _, _ in transitions if t.value == to_status]
    if not matched:
        raise IllegalTransition(from_status, to_status, "no defined transition")

    # 校验 requires
    matched_trans = next((t, action, reqs) for t, action, reqs in transitions if t.value == to_status)
    reqs = matched_trans[2]
    missing = []
    for req in reqs:
        key = req.split()[0] if " " in req else req
        if key not in conditions:
            missing.append(req)
    if missing:
        raise IllegalTransition(from_status, to_status, f"missing required: {missing}")


def next_statuses(from_status: str) -> list[tuple[str, str]]:
    f = ListingStatus(from_status)
    if f in TERMINAL_STATUSES:
        return []
    return [(t.value, action) for t, action, _ in TRANSITIONS.get(f, [])]


def is_terminal(status: str) -> bool:
    try:
        return ListingStatus(status) in TERMINAL_STATUSES
    except ValueError:
        return False