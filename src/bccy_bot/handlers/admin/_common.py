"""管理员 handler 共享工具：权限校验、回应、通用文案。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.repositories import admin_repo
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()


async def ack(update: Update) -> None:
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001
            pass


async def require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, bool]:
    """
    返回 (is_admin, is_super)。

    若非管理员：回复"无权限"并返回 (False, False)。
    通过 session_scope 独立查询（不复用调用方 session 以减少锁竞争）。
    """
    if update.effective_user is None:
        return False, False
    uid = update.effective_user.id
    async with session_scope(context) as session:
        admin = await admin_repo.find_by_telegram_user_id(session, uid)
    if admin is None:
        msg = "⛔ 您无权使用此命令。"
        if update.effective_message is not None:
            try:
                await update.effective_message.reply_text(msg)
            except Exception:  # noqa: BLE001
                pass
        return False, False
    return True, admin.role == "super"


async def require_super(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    is_admin, is_super = await require_admin(update, context)
    if not is_admin:
        return False
    if not is_super:
        msg = "⛔ 该操作仅超级管理员可执行。"
        if update.effective_message is not None:
            try:
                await update.effective_message.reply_text(msg)
            except Exception:  # noqa: BLE001
                pass
        return False
    return True


async def edit_or_reply(update: Update, text: str, reply_markup=None) -> None:
    """callback 时尽量原地编辑；否则发新消息。"""
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
            return
        except Exception:  # noqa: BLE001
            pass
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=reply_markup)
