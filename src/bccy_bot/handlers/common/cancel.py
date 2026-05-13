"""通用「取消当前等待输入」回调 handler。

绑定到 keyboards.awaiting_keyboard.AWT_CANCEL。任何 `set_awaiting(...)` 后被
显示的「❌ 取消当前操作」按钮都会路由到这里：清空 awaiting state，并把消息
编辑为「已取消」。
"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.utils.awaiting import clear_awaiting, get_awaiting

# 与 handlers.inviter.audit.AWAITING_REJECT_KEY 同步（避免循环 import）
_LEGACY_AWAITING_REJECT_KEY = "awaiting_reject_reasons"

log = structlog.get_logger()


async def on_awaiting_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001
            pass
    if update.effective_user is None:
        return
    user_id = update.effective_user.id

    # 主流 awaiting state（admin_awaiting）
    state = get_awaiting(context, user_id)
    kind = state.get("kind") if state else None
    clear_awaiting(context, user_id)

    # 邀请人侧 reject 原因独立 store
    legacy = context.bot_data.get(_LEGACY_AWAITING_REJECT_KEY) or {}
    legacy_app_id = legacy.pop(user_id, None)

    log.info(
        "awaiting_cancelled",
        user_id=user_id,
        kind=kind,
        legacy_app_id=legacy_app_id,
    )

    text = "已取消当前操作。"
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(text)
            return
        except Exception:  # noqa: BLE001
            pass
    if update.effective_message is not None:
        try:
            await update.effective_message.reply_text(text)
        except Exception:  # noqa: BLE001
            pass
