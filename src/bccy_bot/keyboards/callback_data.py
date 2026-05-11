"""
callback_data 命名规范

格式：<scope>:<action>[:<arg>[:<arg>...]]

约束：
- 总长度 <= 64 字节（Telegram API 限制）
- 仅使用 ASCII；不含空格
- scope 三选一：user / inviter / admin
- action 用 snake_case
- args 用 ':' 分隔；含 ':' 或长 ID 时改用紧凑编码
"""

# Scopes
SCOPE_USER = "user"
SCOPE_INVITER = "inviter"
SCOPE_ADMIN = "admin"

# === User actions ===

# 欢迎卡片
USER_START_APPLY = f"{SCOPE_USER}:start_apply"
USER_USE_RECOVERY_KEY = f"{SCOPE_USER}:use_recovery_key"
USER_START_REIMBURSE = f"{SCOPE_USER}:reimburse"  # → 跳转到 rei:start 流程
USER_HELP = f"{SCOPE_USER}:help"

# Wizard 内导航
USER_CANCEL = f"{SCOPE_USER}:cancel"
USER_BACK = f"{SCOPE_USER}:back"

# 选择邀请人（带 ID）
USER_PICK_INVITER_PREFIX = f"{SCOPE_USER}:pick_inviter:"  # + str(inviter_id)
USER_INVITERS_PAGE_PREFIX = f"{SCOPE_USER}:inviters_page:"  # + str(page)

# 预览
USER_PREVIEW_CONFIRM = f"{SCOPE_USER}:preview_confirm"
USER_PREVIEW_REDO = f"{SCOPE_USER}:preview_redo"

# 已有进行中申请提示卡片
USER_VIEW_STATUS = f"{SCOPE_USER}:view_status"
USER_CANCEL_AND_RESTART = f"{SCOPE_USER}:cancel_and_restart"

# 二次确认（取消申请）
USER_CONFIRM_CANCEL = f"{SCOPE_USER}:confirm_cancel"
USER_DISMISS = f"{SCOPE_USER}:dismiss"

SEP = ":"
_MAX_BYTES = 64


def join(*parts: str | int) -> str:
    """拼接 callback_data，自动转字符串并做长度校验。"""
    data = SEP.join(str(p) for p in parts)
    if len(data.encode("utf-8")) > _MAX_BYTES:
        raise ValueError(f"callback_data too long ({len(data)} bytes): {data!r}")
    return data


def parse_inviter_pick(data: str) -> int | None:
    if not data.startswith(USER_PICK_INVITER_PREFIX):
        return None
    try:
        return int(data[len(USER_PICK_INVITER_PREFIX):])
    except ValueError:
        return None


def parse_inviters_page(data: str) -> int | None:
    if not data.startswith(USER_INVITERS_PAGE_PREFIX):
        return None
    try:
        return int(data[len(USER_INVITERS_PAGE_PREFIX):])
    except ValueError:
        return None


# === Inviter actions（审核侧 callback） ===

INVITER_APPROVE_PREFIX = f"{SCOPE_INVITER}:approve:"          # + app_id
INVITER_REJECT_PREFIX = f"{SCOPE_INVITER}:reject:"            # + app_id
INVITER_REJECT_REASON_PREFIX = f"{SCOPE_INVITER}:reject_reason:"  # + app_id
INVITER_REJECT_SKIP_PREFIX = f"{SCOPE_INVITER}:reject_skip:"  # + app_id
INVITER_VIEW_MATERIALS_PREFIX = f"{SCOPE_INVITER}:view_materials:"  # + app_id


def _parse_with_prefix(data: str, prefix: str) -> int | None:
    if not data.startswith(prefix):
        return None
    try:
        return int(data[len(prefix):])
    except ValueError:
        return None


def parse_approve(data: str) -> int | None:
    return _parse_with_prefix(data, INVITER_APPROVE_PREFIX)


def parse_reject(data: str) -> int | None:
    return _parse_with_prefix(data, INVITER_REJECT_PREFIX)


def parse_reject_reason(data: str) -> int | None:
    return _parse_with_prefix(data, INVITER_REJECT_REASON_PREFIX)


def parse_reject_skip(data: str) -> int | None:
    return _parse_with_prefix(data, INVITER_REJECT_SKIP_PREFIX)


def parse_view_materials(data: str) -> int | None:
    return _parse_with_prefix(data, INVITER_VIEW_MATERIALS_PREFIX)
