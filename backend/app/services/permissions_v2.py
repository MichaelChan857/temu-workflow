"""13 权限点对齐 — PRD §13.1

PRD §13.1 列出的权限点：
  1. 批次：查看、创建、取消、重跑
  2. 候选：查看、导入、编辑、合并、重新评估、导出
  3. 一审：查看、通过、驳回、批量审批
  4. 商品资料：生成、编辑、版本回退、图片管理
  5. 二审：查看、通过、退回、驳回
  6. 发布：发起、批量发起、重试、人工关闭
  7. 配置：数据源、评分规则、AI 模型、类目字典、店铺授权、调度
  8. 管理：用户、角色、权限、日志查看、导出

精细化映射每个权限到角色。
"""


# PRD §13.1 → 细粒度权限编码
PERMISSION_CATALOG = {
    # 1. 批次
    "batch.view": "查看批次",
    "batch.create": "创建批次",
    "batch.cancel": "取消批次",
    "batch.replay": "重跑批次",

    # 2. 候选
    "candidate.view": "查看候选",
    "candidate.import": "导入候选",
    "candidate.edit": "编辑候选",
    "candidate.merge": "合并候选",
    "candidate.reevaluate": "重新评估",
    "candidate.export": "导出候选",

    # 3. 一审
    "review.first.view": "查看一审",
    "review.first.approve": "一审通过",
    "review.first.reject": "一审驳回",
    "review.first.batch": "一审批量审批",

    # 4. 商品资料
    "listing.generate": "AI 生成资料",
    "listing.edit": "编辑资料",
    "listing.rollback": "版本回退",
    "listing.image": "图片管理",

    # 5. 二审
    "review.second.view": "查看二审",
    "review.second.approve": "二审通过",
    "review.second.return": "二审退回",
    "review.second.reject": "二审驳回",

    # 6. 发布
    "publish.execute": "发起发布",
    "publish.batch": "批量发布",
    "publish.retry": "重试发布",
    "publish.close": "人工关闭",

    # 7. 配置
    "config.datasource": "数据源",
    "config.score_rule": "评分规则",
    "config.ai_model": "AI 模型",
    "config.category_dict": "类目字典",
    "config.shop_auth": "店铺授权",
    "config.schedule": "调度",

    # 8. 管理
    "user.view": "查看用户",
    "user.create": "创建用户",
    "user.role": "角色管理",
    "user.permission": "权限管理",
    "audit.view": "日志查看",
    "audit.export": "导出日志",
    "alert.view": "告警查看",
    "alert.send": "发送告警",
}


# 6 角色 × 33 权限点 矩阵
ROLE_PERMISSION_MATRIX = {
    "admin": set(PERMISSION_CATALOG.keys()),  # 全部

    "operator": {
        # 选品运营：批次/候选/一审/查看审计/告警
        "batch.view", "batch.create", "batch.cancel",
        "candidate.view", "candidate.import", "candidate.reevaluate",
        "review.first.view", "review.first.approve", "review.first.reject", "review.first.batch",
        "config.datasource", "config.score_rule",
        "audit.view",
        "alert.view",
    },

    "editor": {
        # 商品编辑：候选查看/资料编辑/版本回退/图片/AI 生成
        "candidate.view",
        "listing.generate", "listing.edit", "listing.rollback", "listing.image",
        "review.first.view", "review.first.approve",
    },

    "reviewer": {
        # 上品审核员：一审 + 二审
        "candidate.view",
        "review.first.view", "review.first.approve", "review.first.reject",
        "review.second.view", "review.second.approve", "review.second.return", "review.second.reject",
    },

    "publisher": {
        # 发布操作员：发起/批量/重试/关闭
        "candidate.view",
        "review.second.view",  # 看二审结果
        "publish.execute", "publish.batch", "publish.retry", "publish.close",
        "alert.view",
    },

    "readonly": {
        "batch.view", "candidate.view", "audit.view", "alert.view",
    },
}


def has_permission_v2(user_role: str, permission: str) -> bool:
    """V2 细粒度权限检查（PRD §13.1 对齐）"""
    if user_role == "admin":
        return True
    return permission in ROLE_PERMISSION_MATRIX.get(user_role, set())


def get_role_permissions(role: str) -> set[str]:
    return ROLE_PERMISSION_MATRIX.get(role, set())


def diff_roles(role_a: str, role_b: str) -> set[str]:
    """两个角色的权限差异（用于审计 / 调权）"""
    return get_role_permissions(role_a) ^ get_role_permissions(role_b)