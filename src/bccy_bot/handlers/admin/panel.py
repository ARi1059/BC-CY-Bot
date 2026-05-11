"""/admin 入口 + 主面板渲染 + back 返回。"""

from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin
from bccy_bot.keyboards.admin_factory import main_panel_keyboard
from bccy_bot.utils.awaiting import clear_awaiting


_MAIN_TEXT = (
    "🛠 管理面板\n"
    "─────────────────────────\n"
    "请选择要管理的模块（部分按钮仅超级管理员可见）："
)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admin 命令。"""
    is_admin, is_super = await require_admin(update, context)
    if not is_admin:
        return
    # 进入 /admin 时清空之前可能残留的 awaiting 状态
    if update.effective_user is not None:
        clear_awaiting(context, update.effective_user.id)
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            _MAIN_TEXT, reply_markup=main_panel_keyboard(is_super=is_super)
        )


async def on_back_to_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """返回主面板（callback）。"""
    await ack(update)
    is_admin, is_super = await require_admin(update, context)
    if not is_admin:
        return
    if update.effective_user is not None:
        clear_awaiting(context, update.effective_user.id)
    await edit_or_reply(update, _MAIN_TEXT, reply_markup=main_panel_keyboard(is_super=is_super))


async def on_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """通用关闭。"""
    await ack(update)
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text("已关闭。")
        except Exception:  # noqa: BLE001
            pass
