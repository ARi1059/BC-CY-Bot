"""通用「等待文本输入」状态的取消键盘 + 回调常量。

任何调用 `set_awaiting(...)` 的提示消息都应附带 `cancel_awaiting_keyboard()`，
以便用户无需输入 /cancel 即可点击按钮放弃当前流程。
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

AWT_CANCEL = "awt:cancel"


def cancel_awaiting_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ 取消当前操作", callback_data=AWT_CANCEL)]]
    )
