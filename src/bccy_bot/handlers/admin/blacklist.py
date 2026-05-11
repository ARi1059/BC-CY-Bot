"""黑名单管理：列表 / 添加（文本 Telegram ID + 可选原因）/ 解除。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin
from bccy_bot.keyboards.admin_callbacks import (
    parse_bl_list_page,
    parse_bl_remove,
    parse_bl_remove_confirm,
)
from bccy_bot.keyboards.admin_factory import (
    blacklist_list_keyboard,
    blacklist_remove_confirm_keyboard,
)
from bccy_bot.repositories import admin_repo, blacklist_repo
from bccy_bot.utils.awaiting import clear_awaiting, get_awaiting, set_awaiting
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

AWAIT_KIND = "add_blacklist"


async def on_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return
    page = 0
    if update.callback_query is not None:
        parsed = parse_bl_list_page(update.callback_query.data or "")
        if parsed is not None:
            page = max(0, parsed)
    async with session_scope(context) as session:
        rows = await blacklist_repo.list_all(session)
    text = f"🚫 黑名单（{len(rows)} 条）"
    if not rows:
        text += "\n\n暂无黑名单。点击「➕ 添加黑名单」拉黑用户。"
    await edit_or_reply(update, text, reply_markup=blacklist_list_keyboard(rows, page=page))


async def on_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_KIND, {"step": 1})
    await edit_or_reply(
        update,
        "📝 添加黑名单 · 1/2\n"
        "请发送目标用户的 Telegram 数字 ID（如 123456789）。\n"
        "发送 /cancel 取消。",
    )


async def on_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    bl_id = parse_bl_remove(update.callback_query.data or "")
    if bl_id is None:
        return
    async with session_scope(context) as session:
        from bccy_bot.db.models.blacklist import Blacklist
        bl = await session.get(Blacklist, bl_id)
        if bl is None:
            await edit_or_reply(update, "⚠️ 黑名单条目不存在。")
            return
        tg_id = bl.telegram_user_id
    await edit_or_reply(
        update,
        f"⚠️ 确认解除 {tg_id} 的黑名单？",
        reply_markup=blacklist_remove_confirm_keyboard(bl_id),
    )


async def on_remove_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    bl_id = parse_bl_remove_confirm(update.callback_query.data or "")
    if bl_id is None:
        return
    async with session_scope(context) as session:
        from bccy_bot.db.models.blacklist import Blacklist
        bl = await session.get(Blacklist, bl_id)
        if bl is None:
            await edit_or_reply(update, "⚠️ 已不存在。")
            return
        tg_id = bl.telegram_user_id
        await blacklist_repo.remove(session, bl)
    await edit_or_reply(update, f"✅ 已解除 {tg_id} 的黑名单。")
    log.info("blacklist_removed", telegram_user_id=tg_id)


async def consume_add_blacklist_text(
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
        await update.message.reply_text("已取消添加黑名单。")
        return True

    step = state["data"].get("step", 1)
    if step == 1:
        try:
            uid = int(text)
            if uid <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ 请发送有效的数字 ID。")
            return True
        state["data"]["telegram_user_id"] = uid
        state["data"]["step"] = 2
        await update.message.reply_text(
            "📝 步骤 2/2：请发送拉黑【原因】（可选，发送 /skip 跳过）。"
        )
        return True

    if step == 2:
        reason: str | None
        if text == "/skip":
            reason = None
        else:
            reason = text[:200]
        tg_id = state["data"]["telegram_user_id"]

        async with session_scope(context) as session:
            existing = await blacklist_repo.find_by_telegram_user_id(session, tg_id)
            if existing is not None:
                await update.message.reply_text(f"ℹ️ {tg_id} 已在黑名单中。")
                clear_awaiting(context, update.effective_user.id)
                return True
            adder = await admin_repo.find_by_telegram_user_id(session, update.effective_user.id)
            await blacklist_repo.add(
                session, telegram_user_id=tg_id, reason=reason, added_by=adder.id if adder else None
            )
        await update.message.reply_text(f"✅ 已将 {tg_id} 加入黑名单。")
        log.info("blacklist_added", telegram_user_id=tg_id)
        clear_awaiting(context, update.effective_user.id)
        return True

    return False
