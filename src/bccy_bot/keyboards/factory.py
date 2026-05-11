"""Inline Keyboard 工厂：所有按钮在此集中生成，handler 只消费。"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bccy_bot.keyboards.callback_data import (
    USER_HELP,
    USER_START_APPLY,
    USER_USE_RECOVERY_KEY,
)


def welcome_keyboard() -> InlineKeyboardMarkup:
    """/start 欢迎卡片按钮：开始申请 / 我有回群密钥 / 帮助。"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 开始申请入群", callback_data=USER_START_APPLY)],
            [InlineKeyboardButton("🔑 我有回群密钥", callback_data=USER_USE_RECOVERY_KEY)],
            [InlineKeyboardButton("❓ 帮助", callback_data=USER_HELP)],
        ]
    )
