"""系统配置（仅超级管理员）。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.enums import SK_INVITE_LINK_TTL_HOURS
from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_super
from bccy_bot.keyboards.admin_factory import config_panel_keyboard
from bccy_bot.repositories import settings_repo
from bccy_bot.services import invite_link_service
from bccy_bot.utils.awaiting import clear_awaiting, get_awaiting, set_awaiting
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

AWAIT_KIND = "edit_ttl"


async def on_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    async with session_scope(context) as session:
        ttl = await invite_link_service.get_link_ttl_hours(session)
    text = (
        "⚙️ 系统配置（仅超级管理员）\n"
        "─────────────────────────\n"
        f"📌 邀请链接有效期：{ttl} 小时\n"
        f"📌 单次可用次数：1（固定）\n"
    )
    await edit_or_reply(update, text, reply_markup=config_panel_keyboard())


async def on_edit_ttl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_KIND)
    await edit_or_reply(
        update,
        "✏️ 请发送新的邀请链接有效期（小时，整数，范围 1–168）。\n发送 /cancel 取消。",
    )


async def consume_edit_ttl_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    if update.effective_user is None or update.message is None or update.message.text is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND:
        return False

    text = update.message.text.strip()
    if text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text("已取消修改。")
        return True

    try:
        h = int(text)
    except ValueError:
        await update.message.reply_text("⚠️ 请发送整数。")
        return True

    if not (invite_link_service.MIN_TTL_HOURS <= h <= invite_link_service.MAX_TTL_HOURS):
        await update.message.reply_text(
            f"⚠️ 必须在 {invite_link_service.MIN_TTL_HOURS}–{invite_link_service.MAX_TTL_HOURS} 之间。"
        )
        return True

    async with session_scope(context) as session:
        await settings_repo.set_value(session, SK_INVITE_LINK_TTL_HOURS, str(h))
    await update.message.reply_text(
        f"✅ 邀请链接有效期已更新为 {h} 小时。\n（仅影响修改后新签发的链接，存量链接不变）"
    )
    log.info("invite_link_ttl_updated", hours=h, by=update.effective_user.id)
    clear_awaiting(context, update.effective_user.id)
    return True
