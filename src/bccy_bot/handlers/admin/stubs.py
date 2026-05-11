"""待我审核 / 回群密钥管理 占位（M8 接管完整实现）。"""

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import APP_STATUS_PENDING
from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin
from bccy_bot.keyboards.admin_factory import back_only_keyboard
from bccy_bot.utils.session import session_scope


async def on_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """待我审核：M3 已实现代审分发，这里仅展示当前 pending 总数。"""
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return
    async with session_scope(context) as session:
        count = (
            await session.execute(
                select(func.count(Application.id)).where(Application.status == APP_STATUS_PENDING)
            )
        ).scalar_one()
    text = (
        f"📥 当前待审核申请：{count} 条\n"
        "─────────────────────────\n"
        "代审型申请会自动推送到所有管理员私聊；自审型只推送给对应邀请人。\n"
        "如需重发某条申请的审核材料，可在原推送消息中点「👁 重发审核材料」按钮。"
    )
    await edit_or_reply(update, text, reply_markup=back_only_keyboard())


async def on_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """回群密钥管理：完整管理 UI 在 M8 接管。"""
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return
    text = (
        "🔑 回群密钥管理\n"
        "─────────────────────────\n"
        "完整查询 / 撤销 / 重置功能将在 M8 上线。\n"
        "当前已支持：审核通过自动签发密钥（明文一次性发送给申请人）。"
    )
    await edit_or_reply(update, text, reply_markup=back_only_keyboard())
