"""
callback_data 命名规范

格式：<scope>:<action>[:<arg>[:<arg>...]]

约束：
- 总长度 <= 64 字节（Telegram API 限制）
- 仅使用 ASCII；不含空格
- scope 三选一：user / inviter / admin
- action 用 snake_case
- args 用 ':' 分隔；含 ':' 或长 ID 时改用紧凑编码

示例：
- user:start_apply
- user:select_inviter:42
- inviter:approve:1024
- admin:revoke_key:K2031
"""

# Scopes
SCOPE_USER = "user"
SCOPE_INVITER = "inviter"
SCOPE_ADMIN = "admin"

# User actions
USER_START_APPLY = f"{SCOPE_USER}:start_apply"
USER_USE_RECOVERY_KEY = f"{SCOPE_USER}:use_recovery_key"
USER_HELP = f"{SCOPE_USER}:help"
USER_CANCEL = f"{SCOPE_USER}:cancel"
USER_PREV = f"{SCOPE_USER}:prev"
USER_STATUS = f"{SCOPE_USER}:status"

SEP = ":"


def join(*parts: str | int) -> str:
    """拼接 callback_data，自动转字符串并做长度校验。"""
    data = SEP.join(str(p) for p in parts)
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"callback_data too long ({len(data)} bytes): {data!r}")
    return data
