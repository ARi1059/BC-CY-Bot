"""管理员侧报销审核 callback handlers：通过 / 拒绝 / 重发材料 / 等待口令。"""

import structlog
from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.enums import (
    REI_STATUS_APPROVED,
    REI_STATUS_PENDING,
)
from bccy_bot.db.models.reimbursement_request import ReimbursementRequest
from bccy_bot.keyboards.reimburse_audit_callbacks import (
    parse_approve,
    parse_cancel_wait,
    parse_reject,
    parse_reject_reason,
    parse_reject_skip,
    parse_view,
)
from bccy_bot.repositories import admin_repo, reimbursement_settings
from bccy_bot.services import reimbursement_audit_service as audit
from bccy_bot.services.reimbursement_audit_service import ReimbursementAuditError
from bccy_bot.utils.awaiting import clear_awaiting, get_awaiting, set_awaiting
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

AWAIT_REJECT_REASON_KIND = "rev_reject_reason"
AWAIT_PAYMENT_CODE_KIND = "rev_payment_code"


async def _ack(update: Update) -> None:
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001
            pass


async def _load_pending_with_lock(session, rei_id: int, reviewer_id: int):
    """SELECT FOR UPDATE 加锁；只允许在 pending 状态进入审核。"""
    result = await session.execute(
        select(ReimbursementRequest)
        .where(ReimbursementRequest.id == rei_id)
        .with_for_update()
    )
    r = result.scalar_one_or_none()
    if r is None or r.status != REI_STATUS_PENDING:
        return None
    if r.locked_by != reviewer_id:
        r.locked_by = reviewer_id
        await session.flush()
    return r


async def _load_approved(session, rei_id: int):
    return await session.execute(
        select(ReimbursementRequest).where(
            ReimbursementRequest.id == rei_id,
            ReimbursementRequest.status == REI_STATUS_APPROVED,
        )
    )


async def _authorize_admin(session, telegram_user_id: int) -> bool:
    return await admin_repo.is_admin(session, telegram_user_id)


def _reviewer_display(user) -> str | None:
    if user is None:
        return None
    return f"@{user.username}" if user.username else None


# ---------- 通过 → 进入等待口令 ----------


async def on_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return
    rei_id = parse_approve(update.callback_query.data or "")
    if rei_id is None:
        return

    async with session_scope(context) as session:
        if not await _authorize_admin(session, update.effective_user.id):
            await _reply(update, "⛔ 您无权审核报销。")
            return
        request = await _load_pending_with_lock(session, rei_id, update.effective_user.id)
        if request is None:
            await _reply(update, "⚠️ 该报销已被处理或不存在。")
            return

        try:
            intent = await audit.approve_request_step1(
                session,
                context.bot,
                request,
                reviewer_telegram_id=update.effective_user.id,
                reviewer_display=_reviewer_display(update.effective_user),
            )
        except ReimbursementAuditError as e:
            await _reply(update, f"⚠️ {e}")
            return

    # v1.0.0-beta.4：若 ApprovalIntent.relay_dispatched=True → 已通知口令发放员
    if intent.relay_dispatched:
        await _reply(
            update,
            f"✅ 已批准 #R{intent.reimbursement_id}。\n"
            f"已通知口令发放员（ID {intent.relay_user_id}）私聊 Bot 输入口令。\n"
            "（如需补发 / 接管，可在管理面板「💸 待付款」列表中操作。）",
        )
        return

    # fallback：未配置口令发放员 → 审核者自己输入口令
    set_awaiting(
        context,
        update.effective_user.id,
        AWAIT_PAYMENT_CODE_KIND,
        {"reimbursement_id": intent.reimbursement_id},
    )
    await _reply(
        update,
        f"✅ 已批准 #R{intent.reimbursement_id}。\n"
        "请在下一条消息发送【支付宝口令红包文本】，Bot 将自动转发给申请人。\n"
        "（如需放弃此次发放可发送 /cancel；状态会保留为'已批准待付款'，可在管理面板补发。）",
    )


# ---------- 拒绝（两步） ----------


async def on_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return
    rei_id = parse_reject(update.callback_query.data or "")
    if rei_id is None:
        return

    async with session_scope(context) as session:
        if not await _authorize_admin(session, update.effective_user.id):
            await _reply(update, "⛔ 您无权审核报销。")
            return
        request = await _load_pending_with_lock(session, rei_id, update.effective_user.id)
        if request is None:
            await _reply(update, "⚠️ 该报销已被处理或不存在。")
            return

    # 二级菜单选择是否填原因
    from bccy_bot.services.reimbursement_audit_service import _reject_choice_keyboard  # type: ignore

    try:
        await update.callback_query.edit_message_text(
            f"❓ 是否填写拒绝原因？ (报销 #R{rei_id})",
            reply_markup=_reject_choice_keyboard(rei_id),
        )
    except Exception:  # noqa: BLE001
        await _reply(update, f"❓ 是否填写拒绝原因？ (报销 #R{rei_id})",
                     reply_markup=_reject_choice_keyboard(rei_id))


async def on_reject_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return
    rei_id = parse_reject_reason(update.callback_query.data or "")
    if rei_id is None:
        return
    set_awaiting(
        context,
        update.effective_user.id,
        AWAIT_REJECT_REASON_KIND,
        {"reimbursement_id": rei_id},
    )
    try:
        await update.callback_query.edit_message_text(
            f"✏️ 请发送拒绝原因 (报销 #R{rei_id})\n"
            "发送 /cancel 放弃本次拒绝。"
        )
    except Exception:  # noqa: BLE001
        pass


async def on_reject_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return
    rei_id = parse_reject_skip(update.callback_query.data or "")
    if rei_id is None:
        return

    async with session_scope(context) as session:
        if not await _authorize_admin(session, update.effective_user.id):
            return
        request = await _load_pending_with_lock(session, rei_id, update.effective_user.id)
        if request is None:
            await _reply(update, "⚠️ 该报销已被处理或不存在。")
            return
        try:
            await audit.reject_request(
                session, context.bot, request,
                reviewer_telegram_id=update.effective_user.id,
                reviewer_display=_reviewer_display(update.effective_user),
                reason=None,
            )
        except ReimbursementAuditError as e:
            await _reply(update, f"⚠️ {e}")


async def on_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[👁 重发审核材料]"""
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return
    rei_id = parse_view(update.callback_query.data or "")
    if rei_id is None:
        return
    async with session_scope(context) as session:
        if not await _authorize_admin(session, update.effective_user.id):
            return
        r = await session.get(ReimbursementRequest, rei_id)
        if r is None:
            return
        await audit.repost_materials(
            session, context.bot, r, requester_telegram_id=update.effective_user.id
        )


# ---------- 文本消费器：等待拒绝原因 / 等待口令 ----------


async def consume_reject_reason_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    if update.effective_user is None or update.message is None or update.message.text is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_REJECT_REASON_KIND:
        return False
    text = update.message.text.strip()
    if text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text("已放弃本次拒绝。")
        return True

    rei_id = state["data"].get("reimbursement_id")
    async with session_scope(context) as session:
        if not await _authorize_admin(session, update.effective_user.id):
            clear_awaiting(context, update.effective_user.id)
            await update.message.reply_text("⛔ 您无权审核报销。")
            return True
        request = await session.get(ReimbursementRequest, rei_id)
        if request is None or request.status != REI_STATUS_PENDING:
            clear_awaiting(context, update.effective_user.id)
            await update.message.reply_text("⚠️ 该报销状态已变更，拒绝操作已废弃。")
            return True
        try:
            await audit.reject_request(
                session, context.bot, request,
                reviewer_telegram_id=update.effective_user.id,
                reviewer_display=_reviewer_display(update.effective_user),
                reason=text[:200],
            )
        except ReimbursementAuditError as e:
            await update.message.reply_text(f"⚠️ {e}")
            clear_awaiting(context, update.effective_user.id)
            return True

    clear_awaiting(context, update.effective_user.id)
    await update.message.reply_text("✅ 已拒绝并通知申请人。")
    return True


async def consume_payment_code_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """口令文本消费者：可由管理员（fallback 路径）或口令发放员（v1.0.0-beta.4 主路径）触发。"""
    if update.effective_user is None or update.message is None or update.message.text is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_PAYMENT_CODE_KIND:
        return False
    text = update.message.text.strip()
    if text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text(
            "已放弃本次发放。该报销状态保留为'已批准待付款'，可在 /admin → 报销管理 补发。"
        )
        return True

    rei_id = state["data"].get("reimbursement_id")
    async with session_scope(context) as session:
        # 授权：必须是管理员或当前口令发放员
        is_admin = await _authorize_admin(session, update.effective_user.id)
        relay_id = await reimbursement_settings.get_payment_relay_telegram_id(session)
        is_relay = relay_id > 0 and relay_id == update.effective_user.id
        if not (is_admin or is_relay):
            clear_awaiting(context, update.effective_user.id)
            await update.message.reply_text("⛔ 您无权操作。")
            return True
        request = await session.get(ReimbursementRequest, rei_id)
        if request is None:
            clear_awaiting(context, update.effective_user.id)
            await update.message.reply_text("⚠️ 报销不存在。")
            return True
        if request.status != REI_STATUS_APPROVED:
            clear_awaiting(context, update.effective_user.id)
            await update.message.reply_text("⚠️ 该报销已不在'已批准待付款'状态。")
            return True
        try:
            await audit.confirm_payment(
                session, context.bot, request,
                reviewer_telegram_id=update.effective_user.id,
                reviewer_display=_reviewer_display(update.effective_user),
                payment_code_text=text,
            )
        except ReimbursementAuditError as e:
            await update.message.reply_text(f"⚠️ {e}")
            clear_awaiting(context, update.effective_user.id)
            return True

    clear_awaiting(context, update.effective_user.id)
    await update.message.reply_text("✅ 口令已转发给申请人，报销已发放完成。")
    return True


# ---------- 口令发放员点击 [🧧 输入口令] 按钮 ----------


REL_RELAY_ENTER_PREFIX = "rei:rly:"


def parse_relay_enter(data: str) -> int | None:
    if not data.startswith(REL_RELAY_ENTER_PREFIX):
        return None
    try:
        return int(data[len(REL_RELAY_ENTER_PREFIX):])
    except ValueError:
        return None


async def on_relay_enter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """口令发放员 DM 中收到的 [🧧 输入口令] 按钮回调。设置 awaiting + 提示输入。"""
    await _ack(update)
    if update.effective_user is None or update.callback_query is None:
        return
    rei_id = parse_relay_enter(update.callback_query.data or "")
    if rei_id is None:
        return
    async with session_scope(context) as session:
        relay_id = await reimbursement_settings.get_payment_relay_telegram_id(session)
        if relay_id <= 0 or relay_id != update.effective_user.id:
            await _reply(update, "⛔ 您不是当前配置的口令发放员。")
            return
        request = await session.get(ReimbursementRequest, rei_id)
        if request is None:
            await _reply(update, "⚠️ 该报销不存在。")
            return
        if request.status != REI_STATUS_APPROVED:
            await _reply(update, f"⚠️ 报销 #R{rei_id} 已不在'已批准待付款'状态（当前 {request.status}）。")
            return

    set_awaiting(
        context,
        update.effective_user.id,
        AWAIT_PAYMENT_CODE_KIND,
        {"reimbursement_id": rei_id},
    )
    await _reply(
        update,
        f"🧧 已进入输入状态（#R{rei_id}）。\n"
        "请直接发送【支付宝口令红包文本】，Bot 将自动转发给申请人。\n"
        "发送 /cancel 取消。",
    )


# ---------- 共用 ----------


async def _reply(update: Update, text: str, reply_markup=None) -> None:
    msg = update.effective_message
    if msg is None:
        return
    try:
        await msg.reply_text(text, reply_markup=reply_markup)
    except Exception:  # noqa: BLE001
        pass
