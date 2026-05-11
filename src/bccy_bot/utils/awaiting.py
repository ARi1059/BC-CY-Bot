"""
管理员/审核员"等待文本输入"的状态字典封装。

bot_data["admin_awaiting"][telegram_user_id] = {
    "kind": "add_group" | "add_blacklist" | ...,
    "data": dict[str, Any],  # 累积输入
}

进程重启即丢失（接受）；用户可重新点按钮触发。
"""

from typing import Any

from telegram.ext import ContextTypes

_KEY = "admin_awaiting"


def set_awaiting(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    kind: str,
    data: dict[str, Any] | None = None,
) -> None:
    state = context.bot_data.setdefault(_KEY, {})
    state[user_id] = {"kind": kind, "data": dict(data or {})}


def get_awaiting(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict[str, Any] | None:
    state = context.bot_data.get(_KEY) or {}
    return state.get(user_id)


def clear_awaiting(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    state = context.bot_data.get(_KEY) or {}
    state.pop(user_id, None)


def update_awaiting_data(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, **patch: Any
) -> None:
    entry = get_awaiting(context, user_id)
    if entry is None:
        return
    entry["data"].update(patch)
