"""[🔑 我有回群密钥] 入口 + 密钥文本消费 → 7 条校验 + 一次性新链接。"""

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bccy_bot.keyboards.callback_data import USER_CANCEL
from bccy_bot.services import recovery_key_service
from bccy_bot.utils.awaiting import clear_awaiting, get_awaiting, set_awaiting
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

AWAIT_KIND = "recovery_key_input"


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("« 返回", callback_data=USER_CANCEL)]])


async def on_use_recovery_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """欢迎卡片 [🔑 我有回群密钥] callback：进入"等待密钥输入"状态。"""
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001
            pass
    if update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_KIND)
    text = (
        "🔑 回群密钥兑换\n"
        "─────────────────────────\n"
        "请粘贴您的回群密钥（格式 `BCCY-XXXX-XXXX-XXXX-XXXX`）。\n\n"
        "ℹ️ 此功能仅适用于原账号丢失/封禁后用新账号回群；\n"
        "若与原账号相同将被拦截。"
    )
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=_cancel_keyboard())


async def consume_recovery_key_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """私聊文本消息分发器中调用：若用户在等待输入密钥，则处理之并返回 True。"""
    if update.effective_user is None or update.message is None or update.message.text is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND:
        return False

    text = update.message.text.strip()
    if text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text("已取消密钥兑换。")
        return True

    user = update.effective_user

    async with session_scope(context) as session:
        result = await recovery_key_service.verify_and_consume(
            session,
            context.bot,
            key_plaintext=text,
            claimer_telegram_id=user.id,
            claimer_username=user.username,
        )

    if not result.success:
        await update.message.reply_text(f"⚠️ {result.user_message}")
        # 失败仍维持 awaiting，允许用户重试；仅在 rate_limited / same_id 时清掉防骚扰
        if result.reason_code in ("rate_limited", "same_id", "blacklisted", "inviter_inactive"):
            clear_awaiting(context, user.id)
        return True

    # 成功：发新链接 + 新密钥卡片
    body = [
        "🎉 验证通过！已为您生成新的一次性入群链接。",
        f"邀请人：{result.inviter_display}",
        "",
        f"🔗 加入群组（一次性，24 小时有效）：{result.invite_link_url}",
    ]
    if result.new_key_plaintext:
        body.append("")
        body.append("🔑 您的新回群密钥（请妥善保存）：")
        body.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        body.append(result.new_key_plaintext)
        body.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        body.append("💡 若日后此账号再次丢失，可用更新账号凭此密钥回群。")
    await update.message.reply_text("\n".join(body))
    clear_awaiting(context, user.id)
    return True
