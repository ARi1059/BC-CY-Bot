"""群组管理：列表 / 添加（转发消息识别）/ 移除（含二次确认）。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin
from bccy_bot.keyboards.admin_callbacks import (
    parse_grp_list_page,
    parse_grp_remove,
    parse_grp_remove_confirm,
)
from bccy_bot.keyboards.admin_factory import (
    group_list_keyboard,
    group_remove_confirm_keyboard,
)
from bccy_bot.repositories import group_repo
from bccy_bot.utils.awaiting import clear_awaiting, set_awaiting
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

AWAIT_KIND = "add_group_forward"


async def on_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return

    page = 0
    if update.callback_query is not None:
        parsed = parse_grp_list_page(update.callback_query.data or "")
        if parsed is not None:
            page = max(0, parsed)

    async with session_scope(context) as session:
        groups = await group_repo.list_all(session)

    text = f"👥 群组管理（{len(groups)} 个）"
    if not groups:
        text += "\n\n暂无群组。点击「➕ 添加群组」从转发消息添加。"
    await edit_or_reply(update, text, reply_markup=group_list_keyboard(groups, page=page))


async def on_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[➕ 添加群组] → 提示用户转发目标群的消息。"""
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.effective_user is None:
        return

    set_awaiting(context, update.effective_user.id, AWAIT_KIND)
    text = (
        "📥 请将目标群组中的【任意一条消息】**转发**给我。\n"
        "（Bot 须已在该群中，并具备「邀请用户」权限）\n\n"
        "发送 /cancel 取消。"
    )
    await edit_or_reply(update, text)


async def on_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[🗑 删除] → 二次确认。"""
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return

    group_id = parse_grp_remove(update.callback_query.data or "")
    if group_id is None:
        return

    async with session_scope(context) as session:
        from bccy_bot.db.models.group import Group
        g = await session.get(Group, group_id)
        if g is None:
            await edit_or_reply(update, "⚠️ 群组不存在或已删除。")
            return
        name = g.name
        chat_id = g.telegram_chat_id

    await edit_or_reply(
        update,
        f"⚠️ 确认删除（停用）群组？\n\n📌 {name}\n🆔 {chat_id}",
        reply_markup=group_remove_confirm_keyboard(group_id),
    )


async def on_remove_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return

    group_id = parse_grp_remove_confirm(update.callback_query.data or "")
    if group_id is None:
        return

    async with session_scope(context) as session:
        from bccy_bot.db.models.group import Group
        g = await session.get(Group, group_id)
        if g is None:
            await edit_or_reply(update, "⚠️ 群组不存在。")
            return
        await group_repo.deactivate(session, g)

    await edit_or_reply(update, f"✅ 群组「{g.name}」已停用。", reply_markup=None)
    log.info("group_deactivated", group_id=group_id)


# ---------- 等待转发消息：分发器消费 ----------


async def consume_add_group_forward(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    被消息分发器优先调用：检查当前用户是否在"等待转发添加群组"。
    返回 True 表示已消费。
    """
    if update.effective_user is None or update.message is None:
        return False
    from bccy_bot.utils.awaiting import get_awaiting
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND:
        return False

    if update.message.text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text("已取消添加群组。")
        return True

    msg = update.message
    # 提取被转发消息的来源 chat
    fwd_chat = None
    if getattr(msg, "forward_from_chat", None):
        fwd_chat = msg.forward_from_chat
    elif getattr(msg, "forward_origin", None):
        # PTB v22: ForwardOrigin → 取 chat
        origin = msg.forward_origin
        fwd_chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)

    if fwd_chat is None:
        await msg.reply_text(
            "⚠️ 这不是一条转发自群组的消息。\n"
            "请直接转发目标群中的任意一条消息（不要复制）。"
        )
        return True

    if getattr(fwd_chat, "type", None) not in ("group", "supergroup"):
        await msg.reply_text("⚠️ 该消息来自非群组聊天，无法绑定为目标群组。")
        return True

    async with session_scope(context) as session:
        existing = await group_repo.find_by_telegram_chat_id(session, fwd_chat.id)
        if existing is not None:
            if not existing.is_active:
                existing.is_active = True
                await session.flush()
                await msg.reply_text(f"♻️ 群组「{existing.name}」已重新启用。")
            else:
                await msg.reply_text(f"ℹ️ 群组「{existing.name}」已存在，无需重复添加。")
        else:
            name = fwd_chat.title or f"Chat{fwd_chat.id}"
            g = await group_repo.create(session, telegram_chat_id=fwd_chat.id, name=name)
            await msg.reply_text(f"✅ 群组已添加：「{g.name}」(ID {g.telegram_chat_id})")
            log.info("group_added", group_id=g.id, chat_id=g.telegram_chat_id)

    clear_awaiting(context, update.effective_user.id)
    return True
