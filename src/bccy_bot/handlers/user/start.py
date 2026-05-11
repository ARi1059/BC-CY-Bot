from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.keyboards.factory import welcome_keyboard


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """M0 占位实现：完整 wizard 在 M1 接入。"""
    if update.effective_user is None or update.message is None:
        return

    name = update.effective_user.first_name or "朋友"
    await update.message.reply_text(
        f"👋 你好 {name}！\n\n"
        "欢迎使用 BC-CY-Bot —— 一次性入群邀请审核机器人。\n"
        "（当前为 M0 骨架版本，完整功能将随后续里程碑上线）",
        reply_markup=welcome_keyboard(),
    )
