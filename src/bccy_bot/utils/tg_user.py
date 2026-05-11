"""
Telegram 用户状态判定（[REQ §3.8.5]）。

注销账号识别规则：
- first_name 为空字符串、"Deleted Account"、"已注销账号" 之一
- 或 last_name 与 username 同时为空 + first_name 命中上述特征值
- 或调用 getChat/getChatMember 抛 'chat not found' / 'user is deactivated'

不确定时（API 超时等）按 "normal" 兜底，仅在群内时踢出，不做封禁。
"""

import structlog
from telegram import Bot
from telegram.error import BadRequest

log = structlog.get_logger()

_DEACTIVATED_FIRST_NAMES = ("", "Deleted Account", "已注销账号")
_DEACTIVATED_ERROR_FRAGMENTS = ("user is deactivated", "chat not found")

_PRESENT_STATUSES = ("member", "administrator", "creator", "restricted")
_ADMIN_STATUSES = ("administrator", "creator")


def looks_deactivated(first_name: str | None, last_name: str | None, username: str | None) -> bool:
    """根据 User 字段判定是否注销账号。"""
    if first_name not in _DEACTIVATED_FIRST_NAMES:
        return False
    if last_name or username:
        return False
    return True


async def probe_old_account(
    bot: Bot,
    *,
    target_chat_telegram_id: int,
    old_user_telegram_id: int,
) -> tuple[str, bool, bool]:
    """
    探测原账号在目标群的状态。

    返回 (account_status, in_group, is_chat_admin)：
    - account_status: 'normal' | 'deactivated' | 'unknown'
    - in_group: 是否当前在群中
    - is_chat_admin: 是否为该群的管理员/群主（防止误踢）
    """
    try:
        member = await bot.get_chat_member(target_chat_telegram_id, old_user_telegram_id)
    except BadRequest as e:
        msg = str(e).lower()
        if any(frag in msg for frag in _DEACTIVATED_ERROR_FRAGMENTS):
            return "deactivated", False, False
        log.warning(
            "get_chat_member_failed",
            chat_id=target_chat_telegram_id,
            user_id=old_user_telegram_id,
            err=str(e),
        )
        return "unknown", False, False
    except Exception as e:  # noqa: BLE001
        log.warning(
            "get_chat_member_unexpected",
            chat_id=target_chat_telegram_id,
            user_id=old_user_telegram_id,
            err=str(e),
        )
        return "unknown", False, False

    status = getattr(member, "status", None)
    user = getattr(member, "user", None)

    in_group = status in _PRESENT_STATUSES
    is_admin = status in _ADMIN_STATUSES

    if user is not None and looks_deactivated(
        getattr(user, "first_name", None),
        getattr(user, "last_name", None),
        getattr(user, "username", None),
    ):
        return "deactivated", in_group, is_admin

    return "normal", in_group, is_admin
