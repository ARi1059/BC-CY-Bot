"""Inline Keyboard 工厂：所有按钮在此集中生成，handler 只消费。"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bccy_bot.db.models.inviter import Inviter
from bccy_bot.keyboards.callback_data import (
    USER_BACK,
    USER_CANCEL,
    USER_CANCEL_AND_RESTART,
    USER_CONFIRM_CANCEL,
    USER_DISMISS,
    USER_HELP,
    USER_INVITERS_PAGE_PREFIX,
    USER_PICK_INVITER_PREFIX,
    USER_PREVIEW_CONFIRM,
    USER_PREVIEW_REDO,
    USER_START_APPLY,
    USER_USE_RECOVERY_KEY,
    USER_VIEW_STATUS,
)

INVITERS_PER_PAGE = 6


def welcome_keyboard() -> InlineKeyboardMarkup:
    """/start 欢迎卡片：开始申请 / 我有回群密钥 / 帮助。"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 开始申请入群", callback_data=USER_START_APPLY)],
            [InlineKeyboardButton("🔑 我有回群密钥", callback_data=USER_USE_RECOVERY_KEY)],
            [InlineKeyboardButton("❓ 帮助", callback_data=USER_HELP)],
        ]
    )


def existing_pending_keyboard() -> InlineKeyboardMarkup:
    """已有进行中申请：查看进度 / 取消并重新申请。"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 查看进度", callback_data=USER_VIEW_STATUS)],
            [InlineKeyboardButton("🔄 取消并重新申请", callback_data=USER_CANCEL_AND_RESTART)],
        ]
    )


def inviter_list_keyboard(inviters: list[Inviter], page: int = 0) -> InlineKeyboardMarkup:
    """Step 1：邀请人列表，每页 INVITERS_PER_PAGE 条 + 翻页 + 取消申请。"""
    start = page * INVITERS_PER_PAGE
    end = start + INVITERS_PER_PAGE
    chunk = inviters[start:end]

    rows: list[list[InlineKeyboardButton]] = []
    for inv in chunk:
        label = f"👨‍🏫 {inv.display_name} · {inv.group_label}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{USER_PICK_INVITER_PREFIX}{inv.id}")])

    # 翻页行
    total_pages = (len(inviters) + INVITERS_PER_PAGE - 1) // INVITERS_PER_PAGE
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton("« 上一页", callback_data=f"{USER_INVITERS_PAGE_PREFIX}{page - 1}")
        )
    if page < total_pages - 1:
        nav_row.append(
            InlineKeyboardButton("下一页 »", callback_data=f"{USER_INVITERS_PAGE_PREFIX}{page + 1}")
        )
    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton("❌ 取消申请", callback_data=USER_CANCEL)])
    return InlineKeyboardMarkup(rows)


def material_step_keyboard(*, can_go_back: bool) -> InlineKeyboardMarkup:
    """Step 2：材料收集中的导航按钮。"""
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if can_go_back:
        nav.append(InlineKeyboardButton("« 上一步", callback_data=USER_BACK))
    nav.append(InlineKeyboardButton("❌ 取消申请", callback_data=USER_CANCEL))
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


def preview_keyboard() -> InlineKeyboardMarkup:
    """Step 3：预览页按钮。"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认提交", callback_data=USER_PREVIEW_CONFIRM)],
            [InlineKeyboardButton("✏️ 重新提交", callback_data=USER_PREVIEW_REDO)],
            [InlineKeyboardButton("« 上一步", callback_data=USER_BACK)],
            [InlineKeyboardButton("❌ 取消申请", callback_data=USER_CANCEL)],
        ]
    )


def cancel_confirm_keyboard() -> InlineKeyboardMarkup:
    """取消申请二次确认。"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认取消", callback_data=USER_CONFIRM_CANCEL)],
            [InlineKeyboardButton("« 不取消，继续", callback_data=USER_DISMISS)],
        ]
    )
