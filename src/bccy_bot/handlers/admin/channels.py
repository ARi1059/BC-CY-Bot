"""日志频道 / 出击报告频道绑定（同模式：转发频道消息→识别 chat_id）。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.enums import SK_ATTACK_REPORT_CHANNEL_ID, SK_LOG_CHANNEL_ID
from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin
from bccy_bot.keyboards.admin_factory import channel_panel_keyboard
from bccy_bot.repositories import settings_repo
from bccy_bot.utils.awaiting import clear_awaiting, get_awaiting, set_awaiting
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

KIND_LOG = "bind_log_channel"
KIND_REPORT = "bind_report_channel"


async def on_log_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _panel(update, context, is_log=True)


async def on_report_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _panel(update, context, is_log=False)


async def _panel(update: Update, context: ContextTypes.DEFAULT_TYPE, *, is_log: bool) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return
    key = SK_LOG_CHANNEL_ID if is_log else SK_ATTACK_REPORT_CHANNEL_ID
    async with session_scope(context) as session:
        v = await settings_repo.get(session, key)
    bound_id = int(v) if v else None
    label = "📡 日志频道" if is_log else "📋 出击报告频道"
    text = f"{label}\n─────────────────────────\n"
    if bound_id is None:
        text += "当前未绑定。点击「➕ 绑定频道」开始。"
    else:
        text += f"当前已绑定频道：`{bound_id}`"
    await edit_or_reply(update, text, reply_markup=channel_panel_keyboard(is_log=is_log, bound_id=bound_id))


async def on_log_bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _request_forward(update, context, kind=KIND_LOG, is_log=True)


async def on_report_bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _request_forward(update, context, kind=KIND_REPORT, is_log=False)


async def _request_forward(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, kind: str, is_log: bool
) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, kind)
    label = "日志频道" if is_log else "出击报告频道"
    await edit_or_reply(
        update,
        f"📥 请将目标【{label}】中的【任意一条消息】**转发**到此处。\n"
        "（Bot 须已是该频道的管理员）\n\n发送 /cancel 取消。",
    )


async def on_log_unbind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _unbind(update, context, is_log=True)


async def on_report_unbind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _unbind(update, context, is_log=False)


async def _unbind(update: Update, context: ContextTypes.DEFAULT_TYPE, *, is_log: bool) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return
    key = SK_LOG_CHANNEL_ID if is_log else SK_ATTACK_REPORT_CHANNEL_ID
    async with session_scope(context) as session:
        from bccy_bot.db.models.settings import Setting
        s = await session.get(Setting, key)
        if s is not None:
            await session.delete(s)
            await session.flush()
    await edit_or_reply(update, "✅ 已解绑。")
    log.info("channel_unbound", is_log=is_log)


async def consume_bind_channel_forward(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    if update.effective_user is None or update.message is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") not in (KIND_LOG, KIND_REPORT):
        return False
    kind = state["kind"]
    msg = update.message
    if msg.text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await msg.reply_text("已取消绑定。")
        return True

    fwd_chat = None
    if getattr(msg, "forward_from_chat", None):
        fwd_chat = msg.forward_from_chat
    elif getattr(msg, "forward_origin", None):
        origin = msg.forward_origin
        fwd_chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
    if fwd_chat is None or getattr(fwd_chat, "type", None) != "channel":
        await msg.reply_text("⚠️ 这不是一条从【频道】转发来的消息。请确认转发源是 Channel。")
        return True

    is_log = (kind == KIND_LOG)
    key = SK_LOG_CHANNEL_ID if is_log else SK_ATTACK_REPORT_CHANNEL_ID
    async with session_scope(context) as session:
        await settings_repo.set_value(session, key, str(fwd_chat.id))
    label = "日志频道" if is_log else "出击报告频道"
    await msg.reply_text(f"✅ 已绑定{label}：`{fwd_chat.id}`（{fwd_chat.title or ''}）")
    log.info("channel_bound", is_log=is_log, channel_id=fwd_chat.id)
    clear_awaiting(context, update.effective_user.id)
    return True
