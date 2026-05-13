"""通用「取消当前等待输入」回调 handler。

绑定到 keyboards.awaiting_keyboard.AWT_CANCEL。点击「❌ 取消当前操作」时：

1. 清空 awaiting state（主 store 与遗留 inviter reject store 都清）
2. 根据被取消的 `kind` 把当前消息**原地编辑**为对应的返回面板，
   形成「文本输入 → 取消 → 回到上一级面板」的闭环
3. 找不到合适的返回目标时退化为「已取消」文本提示
"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.keyboards.factory import welcome_keyboard
from bccy_bot.utils.awaiting import clear_awaiting, get_awaiting

# 与 handlers.inviter.audit.AWAITING_REJECT_KEY 同步（避免循环 import）
_LEGACY_AWAITING_REJECT_KEY = "awaiting_reject_reasons"

log = structlog.get_logger()


# kind → (module path, attribute name) 的映射。
# 用 lazy import 避免循环依赖。
_ADMIN_RETURN_BY_KIND: dict[str, tuple[str, str]] = {
    # 列表型：取消后回到对应列表面板
    "add_inviter":          ("bccy_bot.handlers.admin.inviters",      "on_list"),
    "add_teacher":          ("bccy_bot.handlers.admin.teachers",      "on_list"),
    "tea_set_group":        ("bccy_bot.handlers.admin.teachers",      "on_list"),
    "add_blacklist":        ("bccy_bot.handlers.admin.blacklist",     "on_list"),
    "add_sub_admin":        ("bccy_bot.handlers.admin.admin_mgmt",    "on_list"),
    "add_group_forward":    ("bccy_bot.handlers.admin.groups",        "on_list"),
    # 频道绑定：回到该频道的面板
    "bind_log_channel":     ("bccy_bot.handlers.admin.channels",      "on_log_panel"),
    "bind_report_channel":  ("bccy_bot.handlers.admin.channels",      "on_report_panel"),
    # 系统配置
    "edit_ttl":             ("bccy_bot.handlers.admin.settings_ui",   "on_panel"),
    # 报销系统配置（5 项设置共用 settings 面板）
    "rei_set_budget":         ("bccy_bot.handlers.admin.reimbursement", "on_settings_panel"),
    "rei_set_cooldown":       ("bccy_bot.handlers.admin.reimbursement", "on_settings_panel"),
    "rei_set_reset_day":      ("bccy_bot.handlers.admin.reimbursement", "on_settings_panel"),
    "rei_set_payment_relay_id": ("bccy_bot.handlers.admin.reimbursement", "on_settings_panel"),
    # 报销资格列表
    "rei_elig_forward":     ("bccy_bot.handlers.admin.reimbursement", "on_eligibility_panel"),
    # 用户冷却覆盖
    "rei_override_input":   ("bccy_bot.handlers.admin.reimbursement", "on_overrides_panel"),
    # 报销审核流程：拒绝原因 → 回到待审核列表；口令录入 → 回到报销主面板
    "rev_reject_reason":    ("bccy_bot.handlers.admin.reimbursement", "on_pending_list"),
    "rev_payment_code":     ("bccy_bot.handlers.admin.reimbursement", "on_panel"),
}


async def _dispatch_to_panel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, module_path: str, attr: str
) -> bool:
    """Lazy-import 目标 panel 渲染函数并调用；失败返回 False。"""
    try:
        from importlib import import_module
        mod = import_module(module_path)
        fn = getattr(mod, attr)
        await fn(update, context)
        return True
    except Exception:  # noqa: BLE001
        log.exception("cancel_return_panel_failed", module=module_path, attr=attr)
        return False


async def _render_welcome_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """用户侧：把当前消息编辑回欢迎卡片（用于 recovery_key_input 取消后）。"""
    if update.effective_user is None or update.callback_query is None:
        return False
    name = update.effective_user.first_name or "朋友"
    text = (
        f"👋 你好 {name}！\n\n"
        "欢迎使用 BC-CY-Bot —— 一次性入群邀请审核机器人。\n"
        "请选择下方操作："
    )
    try:
        await update.callback_query.edit_message_text(text, reply_markup=welcome_keyboard())
        return True
    except Exception:  # noqa: BLE001
        log.exception("cancel_render_welcome_failed")
        return False


async def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """轻量级 admin 校验，用于路由前判定。"""
    if update.effective_user is None:
        return False
    try:
        from bccy_bot.repositories import admin_repo
        from bccy_bot.utils.session import session_scope
        async with session_scope(context) as session:
            return await admin_repo.is_admin(session, update.effective_user.id)
    except Exception:  # noqa: BLE001
        log.exception("cancel_admin_check_failed")
        return False


async def _render_return_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    kind: str | None,
    legacy_app_id: int | None,
) -> bool:
    """根据 kind 派发到对应面板；找不到 / 无权限则返回 False（落 fallback 文本）。"""
    if kind == "recovery_key_input":
        return await _render_welcome_card(update, context)

    if kind is None:
        return False

    target = _ADMIN_RETURN_BY_KIND.get(kind)
    if target is None:
        return False

    # rev_payment_code 也可能由非 admin 的口令发放员触发；这种情况下跳到 admin
    # 面板会被 require_admin 拒绝并污染聊天，故先检查身份再决定。
    if kind == "rev_payment_code" and not await _is_admin(update, context):
        return False

    return await _dispatch_to_panel(update, context, *target)


async def on_awaiting_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 先 ack（含轻量级 toast 提示），便于用户立即感知点击生效
    if update.callback_query is not None:
        try:
            await update.callback_query.answer("已取消")
        except Exception:  # noqa: BLE001
            pass
    if update.effective_user is None:
        return
    user_id = update.effective_user.id

    # 1. 清空主 awaiting state
    state = get_awaiting(context, user_id)
    kind = state.get("kind") if state else None
    clear_awaiting(context, user_id)

    # 2. 清空邀请人 reject 原因 legacy store
    legacy = context.bot_data.get(_LEGACY_AWAITING_REJECT_KEY) or {}
    legacy_app_id = legacy.pop(user_id, None)

    log.info(
        "awaiting_cancelled",
        user_id=user_id,
        kind=kind,
        legacy_app_id=legacy_app_id,
    )

    # 3. 根据 kind 编辑当前消息为对应的返回面板
    if await _render_return_panel(update, context, kind, legacy_app_id):
        return

    # 4. Fallback：仅文本提示
    fallback = "已取消当前操作。\n如需继续，请发送 /admin（管理员）或 /start（用户）。"
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(fallback)
            return
        except Exception:  # noqa: BLE001
            pass
    if update.effective_message is not None:
        try:
            await update.effective_message.reply_text(fallback)
        except Exception:  # noqa: BLE001
            pass
