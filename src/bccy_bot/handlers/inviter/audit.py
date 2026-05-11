"""审核者 callback handlers：通过 / 拒绝 / 重发材料。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import APP_STATUS_PENDING, REVIEW_MODE_SELF
from bccy_bot.keyboards.callback_data import (
    parse_approve,
    parse_reject,
    parse_reject_reason,
    parse_reject_skip,
    parse_view_materials,
)
from bccy_bot.keyboards.factory import reject_choice_keyboard
from bccy_bot.repositories import inviter_repo
from bccy_bot.services import audit_service
from bccy_bot.services.audit_service import AuditError
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

AWAITING_REJECT_KEY = "awaiting_reject_reasons"


async def _ack(update: Update) -> None:
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001
            pass


async def _load_pending(session, app_id: int) -> Application | None:
    app = await session.get(Application, app_id)
    if app is None or app.status != APP_STATUS_PENDING:
        return None
    return app


async def _authorize(session, application: Application, reviewer_telegram_id: int) -> tuple[bool, str]:
    """
    返回 (是否有权审核, 角色名'inviter'|'admin')。

    M2 仅支持自审型：reviewer 必须是 inviter.telegram_user_id。
    M3 会扩展代审型（任一管理员可审核）。
    """
    if application.inviter_id is None:
        return False, "inviter"
    inv = await inviter_repo.get_by_id(session, application.inviter_id)
    if inv is None:
        return False, "inviter"
    if inv.review_mode == REVIEW_MODE_SELF and inv.telegram_user_id == reviewer_telegram_id:
        return True, "inviter"
    # TODO(M3): 代审型 + 管理员校验
    return False, "inviter"


# ---------- 通过 ----------


async def on_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return

    app_id = parse_approve(update.callback_query.data or "")
    if app_id is None:
        return

    async with session_scope(context) as session:
        app = await _load_pending(session, app_id)
        if app is None:
            if update.effective_message is not None:
                await update.effective_message.reply_text(
                    "⚠️ 该申请已被处理或不存在。"
                )
            return

        authorized, role = await _authorize(session, app, update.effective_user.id)
        if not authorized:
            if update.effective_message is not None:
                await update.effective_message.reply_text("⚠️ 您无权审核此申请。")
            return

        try:
            result = await audit_service.approve_application(
                session,
                context.bot,
                app,
                reviewer_telegram_id=update.effective_user.id,
                reviewer_role=role,
                reviewer_display=f"@{update.effective_user.username}" if update.effective_user.username else None,
            )
        except AuditError as e:
            if update.effective_message is not None:
                await update.effective_message.reply_text(f"⚠️ {e}")
            return

    log.info("approve_handler_done", application_id=app_id, link_url=result.invite_link_url[:40] + "...")


# ---------- 拒绝（两步） ----------


async def on_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[❌ 拒绝] → 展示二级选择。"""
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return

    app_id = parse_reject(update.callback_query.data or "")
    if app_id is None:
        return

    async with session_scope(context) as session:
        app = await _load_pending(session, app_id)
        if app is None:
            if update.effective_message is not None:
                await update.effective_message.reply_text("⚠️ 该申请已被处理或不存在。")
            return
        authorized, _ = await _authorize(session, app, update.effective_user.id)
        if not authorized:
            if update.effective_message is not None:
                await update.effective_message.reply_text("⚠️ 您无权审核此申请。")
            return

    try:
        await update.callback_query.edit_message_text(
            f"❓ 是否填写拒绝原因？ (申请 #{app_id})",
            reply_markup=reject_choice_keyboard(app_id),
        )
    except Exception:  # noqa: BLE001
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                f"❓ 是否填写拒绝原因？ (申请 #{app_id})",
                reply_markup=reject_choice_keyboard(app_id),
            )


async def on_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[✏️ 填写原因] → 设置 awaiting 状态，等待下一条文本。"""
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return

    app_id = parse_reject_reason(update.callback_query.data or "")
    if app_id is None:
        return

    awaiting = context.bot_data.setdefault(AWAITING_REJECT_KEY, {})
    awaiting[update.effective_user.id] = app_id

    try:
        await update.callback_query.edit_message_text(
            f"✏️ 请在下一条消息中发送【拒绝原因】(申请 #{app_id})\n"
            "（5 分钟内有效；发送 /cancel 放弃本次拒绝。）"
        )
    except Exception:  # noqa: BLE001
        pass


async def on_reject_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[⏩ 跳过直接拒绝] → 无原因拒绝。"""
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return

    app_id = parse_reject_skip(update.callback_query.data or "")
    if app_id is None:
        return

    async with session_scope(context) as session:
        app = await _load_pending(session, app_id)
        if app is None:
            if update.effective_message is not None:
                await update.effective_message.reply_text("⚠️ 该申请已被处理或不存在。")
            return
        authorized, role = await _authorize(session, app, update.effective_user.id)
        if not authorized:
            if update.effective_message is not None:
                await update.effective_message.reply_text("⚠️ 您无权审核此申请。")
            return

        try:
            await audit_service.reject_application(
                session,
                context.bot,
                app,
                reviewer_telegram_id=update.effective_user.id,
                reviewer_role=role,
                reason=None,
                reviewer_display=f"@{update.effective_user.username}" if update.effective_user.username else None,
            )
        except AuditError as e:
            if update.effective_message is not None:
                await update.effective_message.reply_text(f"⚠️ {e}")
            return


async def consume_reject_reason_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    被消息分发器优先调用：检查当前用户是否在 awaiting 状态。
    返回 True 表示已消费此消息（无需继续走 wizard 逻辑）。
    """
    if update.effective_user is None or update.message is None or update.message.text is None:
        return False

    awaiting = context.bot_data.get(AWAITING_REJECT_KEY) or {}
    app_id = awaiting.get(update.effective_user.id)
    if app_id is None:
        return False

    text = update.message.text.strip()
    if text == "/cancel":
        awaiting.pop(update.effective_user.id, None)
        await update.message.reply_text("已放弃本次拒绝操作。")
        return True

    async with session_scope(context) as session:
        app = await _load_pending(session, app_id)
        if app is None:
            awaiting.pop(update.effective_user.id, None)
            await update.message.reply_text("⚠️ 申请状态已变更，拒绝操作已废弃。")
            return True

        authorized, role = await _authorize(session, app, update.effective_user.id)
        if not authorized:
            awaiting.pop(update.effective_user.id, None)
            await update.message.reply_text("⚠️ 您无权审核此申请。")
            return True

        try:
            await audit_service.reject_application(
                session,
                context.bot,
                app,
                reviewer_telegram_id=update.effective_user.id,
                reviewer_role=role,
                reason=text,
                reviewer_display=f"@{update.effective_user.username}"
                if update.effective_user.username
                else None,
            )
        except AuditError as e:
            await update.message.reply_text(f"⚠️ {e}")
            awaiting.pop(update.effective_user.id, None)
            return True

    awaiting.pop(update.effective_user.id, None)
    await update.message.reply_text("✅ 已拒绝，并通知申请人。")
    return True


# ---------- 重发审核材料 ----------


async def on_view_materials(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return

    app_id = parse_view_materials(update.callback_query.data or "")
    if app_id is None:
        return

    async with session_scope(context) as session:
        app = await session.get(Application, app_id)
        if app is None:
            return
        authorized, _ = await _authorize(session, app, update.effective_user.id)
        if not authorized:
            return
        await audit_service.repost_materials(
            session,
            context.bot,
            app,
            requester_telegram_id=update.effective_user.id,
        )
