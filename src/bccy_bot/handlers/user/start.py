import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.enums import APP_STATUS_PENDING, APP_STATUS_WIZARD
from bccy_bot.handlers.user.render import (
    render_blacklisted,
    render_existing_pending,
    render_existing_wizard,
)
from bccy_bot.keyboards.factory import existing_pending_keyboard, welcome_keyboard
from bccy_bot.repositories import application_repo, blacklist_repo
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start 入口：黑名单 / 已有进行中申请 / 全新用户三分支。"""
    if update.effective_user is None or update.message is None:
        return

    user = update.effective_user

    async with session_scope(context) as session:
        if await blacklist_repo.is_blacklisted(session, user.id):
            log.info("blacklisted_start_attempt", telegram_user_id=user.id)
            # REQ §7 静默拒绝 + 简短提示（避免泄露黑名单细节）
            await update.message.reply_text(render_blacklisted())
            return

        existing = await application_repo.get_active_for_user(session, user.id)

    if existing is not None:
        if existing.status == APP_STATUS_PENDING:
            await update.message.reply_text(
                render_existing_pending(),
                reply_markup=existing_pending_keyboard(),
            )
            return
        if existing.status == APP_STATUS_WIZARD:
            await update.message.reply_text(
                render_existing_wizard(),
                reply_markup=existing_pending_keyboard(),
            )
            return

    name = user.first_name or "朋友"
    await update.message.reply_text(
        f"👋 你好 {name}！\n\n"
        "欢迎使用 BC-CY-Bot —— 一次性入群邀请审核机器人。\n"
        "请选择下方操作：",
        reply_markup=welcome_keyboard(),
    )
