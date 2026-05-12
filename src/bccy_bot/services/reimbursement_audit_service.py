"""
报销审核流程（[REQ §8.5.4]）。

职责：
- pending 报销到达后广播给所有管理员（双消息）
- 通过：行锁 + 预算复检 + 扣减预算 + 进入"等待口令"状态
- 等待口令：审核者私聊发文本 → 保存口令 → 转发给申请人 → status=paid
- 拒绝：同 v1 审核拒绝流程
- 行锁保证多管理员并发只成功一次
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram import Bot
from telegram.error import BadRequest, TelegramError
from telegram.constants import ParseMode

from bccy_bot.db.models.audit_log import AuditLog
from bccy_bot.db.models.enums import (
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REI_STATUS_APPROVED,
    REI_STATUS_PAID,
    REI_STATUS_PENDING,
    REI_STATUS_REJECTED,
)
from bccy_bot.db.models.reimbursement_audit_message import ReimbursementAuditMessage
from bccy_bot.db.models.reimbursement_material import ReimbursementMaterial
from bccy_bot.db.models.reimbursement_request import ReimbursementRequest
from bccy_bot.keyboards.reimburse_audit_callbacks import (
    REV_APPROVE_PREFIX,
    REV_REJECT_PREFIX,
    REV_REJECT_REASON_PREFIX,
    REV_REJECT_SKIP_PREFIX,
    REV_VIEW_PREFIX,
)
from bccy_bot.repositories import (
    admin_repo,
    reimbursement_repo,
    reimbursement_settings,
)
from bccy_bot.services import log_channel_service
from bccy_bot.utils.retry import telegram_retry

log = structlog.get_logger()

MEDIA_CAPTION_MAX = 1024


class ReimbursementAuditError(Exception):
    pass


# ---------- 文案与键盘渲染 ----------


def _audit_keyboard(rei_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ 通过", callback_data=f"{REV_APPROVE_PREFIX}{rei_id}"),
                InlineKeyboardButton("❌ 拒绝", callback_data=f"{REV_REJECT_PREFIX}{rei_id}"),
            ],
            [InlineKeyboardButton("👁 重发审核材料", callback_data=f"{REV_VIEW_PREFIX}{rei_id}")],
        ]
    )


def _reject_choice_keyboard(rei_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ 填写原因", callback_data=f"{REV_REJECT_REASON_PREFIX}{rei_id}")],
            [InlineKeyboardButton("⏩ 跳过直接拒绝", callback_data=f"{REV_REJECT_SKIP_PREFIX}{rei_id}")],
        ]
    )


def _split_materials(
    materials: list[ReimbursementMaterial],
) -> tuple[list[ReimbursementMaterial], str | None]:
    by_type: dict[str, ReimbursementMaterial] = {m.material_type: m for m in materials}
    photos: list[ReimbursementMaterial] = []
    for mt in (MAT_BOOKING, MAT_GESTURE):
        m = by_type.get(mt)
        if m is not None and m.content_type == CT_PHOTO and m.telegram_file_id:
            photos.append(m)
    report = by_type.get(MAT_REPORT)
    report_text = report.text_content if report and report.content_type == CT_TEXT else None
    return photos, report_text


async def _build_summary(
    session: AsyncSession, request: ReimbursementRequest
) -> str:
    username_part = (
        f"@{request.applicant_username}" if request.applicant_username else "（无用户名）"
    )
    submitted = (
        request.submitted_at.strftime("%Y-%m-%d %H:%M")
        if request.submitted_at
        else "—"
    )
    amount_yuan = reimbursement_settings.cents_to_yuan_display(request.amount_cents)

    # 该用户近 30 天报销次数
    from datetime import timedelta

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    history_30d = await reimbursement_repo.count_in_range_for_user(
        session,
        applicant_telegram_id=request.applicant_telegram_id,
        start=start,
        end=end,
    )

    return (
        f"💰 新报销待审核 #R{request.id}\n"
        "─────────────────────────\n"
        f"👤 申请人：{username_part}\n"
        f"🆔 ID：{request.applicant_telegram_id}\n"
        f"💵 金额：{amount_yuan} 元\n"
        f"📊 近 30 天报销次数：{history_30d}\n"
        f"🕐 提交时间：{submitted}"
    )


# ---------- Telegram 调用（带 retry） ----------


@telegram_retry(max_attempts=3)
async def _send_media_group(bot: Bot, chat_id: int, media: list[InputMediaPhoto]):
    return await bot.send_media_group(chat_id=chat_id, media=media)


@telegram_retry(max_attempts=3)
async def _send_text(bot: Bot, chat_id: int, text: str, reply_markup=None):
    return await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


@telegram_retry(max_attempts=3)
async def _edit_text(bot: Bot, chat_id: int, message_id: int, text: str):
    return await bot.edit_message_text(
        chat_id=chat_id, message_id=message_id, text=text, reply_markup=None
    )


# ---------- 主入口：通知审核者 ----------


async def notify_admins(
    session: AsyncSession, bot: Bot, request: ReimbursementRequest
) -> None:
    """pending 报销触发：广播给所有管理员。"""
    if request.status != REI_STATUS_PENDING:
        return

    admins = await admin_repo.list_all(session)
    if not admins:
        log.warning("rei_notify_no_admins", reimbursement_id=request.id)
        return

    materials = await reimbursement_repo.list_materials(session, request.id)
    photos, report_text = _split_materials(materials)
    summary = await _build_summary(session, request)

    # 日志频道：📥 新报销
    try:
        await log_channel_service.push_reimbursement_event(
            session, bot,
            kind="new",
            reimbursement_id=request.id,
            applicant_telegram_id=request.applicant_telegram_id,
            applicant_username=request.applicant_username,
            amount_cents=request.amount_cents,
        )
    except Exception:  # noqa: BLE001
        log.exception("rei_log_new_failed", reimbursement_id=request.id)

    for adm in admins:
        try:
            await _push_to_reviewer(
                session, bot,
                request=request,
                reviewer_chat_id=adm.telegram_user_id,
                photos=photos,
                report_text=report_text,
                summary_text=summary,
            )
        except BadRequest as e:
            log.warning(
                "rei_notify_push_failed",
                reimbursement_id=request.id,
                admin_id=adm.telegram_user_id,
                err=str(e),
            )


async def _push_to_reviewer(
    session: AsyncSession,
    bot: Bot,
    *,
    request: ReimbursementRequest,
    reviewer_chat_id: int,
    photos: list[ReimbursementMaterial],
    report_text: str | None,
    summary_text: str,
) -> ReimbursementAuditMessage:
    media_msg_id: int | None = None
    report_msg_id: int | None = None
    long_report = (report_text is not None and len(report_text) > MEDIA_CAPTION_MAX)

    if photos:
        caption = report_text if (report_text and not long_report) else None
        media = [
            InputMediaPhoto(media=p.telegram_file_id, caption=(caption if i == 0 else None))
            for i, p in enumerate(photos)
        ]
        sent = await _send_media_group(bot, reviewer_chat_id, media)
        if sent:
            media_msg_id = sent[0].message_id

        if long_report and report_text:
            sent_report = await _send_text(bot, reviewer_chat_id, f"📝 出击报告：\n{report_text}")
            report_msg_id = sent_report.message_id
    elif report_text:
        summary_text = f"{summary_text}\n\n📝 出击报告：\n{report_text}"

    button_msg = await _send_text(
        bot, reviewer_chat_id, summary_text, reply_markup=_audit_keyboard(request.id)
    )

    row = ReimbursementAuditMessage(
        reimbursement_id=request.id,
        reviewer_telegram_id=reviewer_chat_id,
        media_message_id=media_msg_id,
        text_message_id=button_msg.message_id,
        report_message_id=report_msg_id,
    )
    session.add(row)
    await session.flush()
    return row


# ---------- 通过流程 ----------


@dataclass
class ApprovalIntent:
    """approve 第一阶段返回。

    relay_dispatched=True 表示已 DM 给口令发放员；handler 不应再设置审核者的 awaiting。
    relay_dispatched=False 表示 fallback 到原管理员输入；handler 仍按 v1.0.0-beta.3 设置审核者 awaiting。
    """
    reimbursement_id: int
    amount_cents: int
    relay_dispatched: bool = False
    relay_user_id: int | None = None


# 口令发放员侧 "🧧 输入口令" 按钮的 callback prefix
REL_RELAY_ENTER_PREFIX = "rei:rly:"


def _relay_entry_keyboard(reimbursement_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🧧 输入口令", callback_data=f"{REL_RELAY_ENTER_PREFIX}{reimbursement_id}")]]
    )


async def _dispatch_to_relay(
    bot: Bot,
    *,
    relay_user_id: int,
    request: ReimbursementRequest,
    reviewer_display: str | None,
) -> bool:
    """向口令发放员发 DM + 按钮；返回是否发送成功。"""
    amount_yuan = reimbursement_settings.cents_to_yuan_display(request.amount_cents)
    applicant_label = (
        f"@{request.applicant_username}" if request.applicant_username
        else f"#{request.applicant_telegram_id}"
    )
    text = (
        f"💸 待发放报销 · #{request.id}\n"
        f"─────────────────────────\n"
        f"申请人：{applicant_label}\n"
        f"金额：{amount_yuan} 元\n"
        f"审核者：{reviewer_display or '—'}\n\n"
        f"点击下方按钮进入口令输入状态（5 分钟内有效）。"
    )
    try:
        await bot.send_message(
            chat_id=relay_user_id,
            text=text,
            reply_markup=_relay_entry_keyboard(request.id),
        )
        return True
    except TelegramError as e:
        log.warning(
            "rei_relay_dm_failed",
            relay_user_id=relay_user_id,
            reimbursement_id=request.id,
            err=str(e),
        )
        return False


async def approve_request_step1(
    session: AsyncSession,
    bot: Bot,
    request: ReimbursementRequest,
    *,
    reviewer_telegram_id: int,
    reviewer_display: str | None = None,
) -> ApprovalIntent:
    """
    审核第一阶段：通过 + 预算复检 + 扣减 + 状态→approved。
    返回 ApprovalIntent，handler 据此设置 awaiting 状态并提示发送口令。

    本函数不修改 paid_at / alipay_code_text；那是 confirm_payment 的事。
    """
    if request.status != REI_STATUS_PENDING:
        raise ReimbursementAuditError("该报销已不在待审核状态")

    # 预算复检
    remaining = await reimbursement_settings.get_monthly_remaining_cents(session)
    if remaining < request.amount_cents:
        # 直接拒绝：预算不足
        await reject_request(
            session, bot, request,
            reviewer_telegram_id=reviewer_telegram_id,
            reviewer_display=reviewer_display,
            reason="本月预算已用尽，已退回",
            is_budget_reject=True,
        )
        raise ReimbursementAuditError("本月预算不足，该申请已自动退回")

    # 扣减预算
    await reimbursement_settings.set_monthly_remaining_cents(
        session, remaining - request.amount_cents
    )

    # 状态更新
    request.status = REI_STATUS_APPROVED
    request.reviewed_at = datetime.now(timezone.utc)
    request.reviewed_by_telegram_id = reviewer_telegram_id
    await session.flush()

    session.add(
        AuditLog(
            actor_telegram_id=reviewer_telegram_id,
            actor_role="admin",
            action="reimbursement_approve",
            target_application_id=None,
            details={"reimbursement_id": request.id, "amount_cents": request.amount_cents},
        )
    )

    # 编辑所有审核消息为"已通过待付款"
    await _edit_audit_messages(
        session, bot,
        reimbursement_id=request.id,
        reviewer_display=reviewer_display,
        reviewer_telegram_id=reviewer_telegram_id,
        marker_text=f"✅ 已通过 by {reviewer_display or f'#{reviewer_telegram_id}'} · 待付款",
    )

    # 日志频道
    try:
        await log_channel_service.push_reimbursement_event(
            session, bot,
            kind="approved",
            reimbursement_id=request.id,
            applicant_telegram_id=request.applicant_telegram_id,
            applicant_username=request.applicant_username,
            amount_cents=request.amount_cents,
            reviewer_telegram_id=reviewer_telegram_id,
            reviewer_display=reviewer_display,
        )
    except Exception:  # noqa: BLE001
        log.exception("rei_log_approved_failed", reimbursement_id=request.id)

    log.info(
        "reimbursement_approved",
        reimbursement_id=request.id,
        reviewer_id=reviewer_telegram_id,
        budget_remaining=remaining - request.amount_cents,
    )

    # v1.0.0-beta.4：若配置了口令发放员，DM 给他/她；handler 不再设置审核者 awaiting
    relay_user_id = await reimbursement_settings.get_payment_relay_telegram_id(session)
    if relay_user_id and relay_user_id > 0:
        dispatched = await _dispatch_to_relay(
            bot,
            relay_user_id=relay_user_id,
            request=request,
            reviewer_display=reviewer_display,
        )
        if dispatched:
            log.info(
                "rei_relay_dispatched",
                reimbursement_id=request.id,
                relay_user_id=relay_user_id,
            )
            return ApprovalIntent(
                reimbursement_id=request.id,
                amount_cents=request.amount_cents,
                relay_dispatched=True,
                relay_user_id=relay_user_id,
            )
        # 发送失败：fallback 到审核者输入
        log.warning(
            "rei_relay_fallback_to_reviewer",
            reimbursement_id=request.id,
            relay_user_id=relay_user_id,
        )

    return ApprovalIntent(reimbursement_id=request.id, amount_cents=request.amount_cents)


async def confirm_payment(
    session: AsyncSession,
    bot: Bot,
    request: ReimbursementRequest,
    *,
    reviewer_telegram_id: int,
    reviewer_display: str | None,
    payment_code_text: str,
) -> None:
    """
    审核第二阶段：审核者发来口令文本 → 保存 + 转发给申请人 + status=paid。
    """
    if request.status != REI_STATUS_APPROVED:
        raise ReimbursementAuditError("该报销已不在'待付款'状态")

    code = payment_code_text.strip()
    if not code:
        raise ReimbursementAuditError("口令不能为空")

    request.alipay_code_text = code
    request.paid_at = datetime.now(timezone.utc)
    request.paid_by_telegram_id = reviewer_telegram_id
    request.status = REI_STATUS_PAID
    await session.flush()

    session.add(
        AuditLog(
            actor_telegram_id=reviewer_telegram_id,
            actor_role="admin",
            action="reimbursement_pay",
            target_application_id=None,
            details={"reimbursement_id": request.id, "amount_cents": request.amount_cents},
        )
    )

    # 转发口令给申请人（v1.0.0-beta.4：行内代码样式，点击/长按可复制）
    amount_yuan = reimbursement_settings.cents_to_yuan_display(request.amount_cents)
    text_html = (
        f"🎁 您的报销已批准并发放！\n"
        f"金额：{amount_yuan} 元\n\n"
        f"口令（点击/长按可复制）：\n"
        f"<code>{html_escape(code)}</code>\n\n"
        f"请复制此口令在支付宝中兑换。"
    )
    try:
        await bot.send_message(
            chat_id=request.applicant_telegram_id,
            text=text_html,
            parse_mode=ParseMode.HTML,
        )
    except BadRequest as e:
        log.error("rei_payment_send_failed", reimbursement_id=request.id, err=str(e))
        # 兜底：如果 HTML 解析失败（例如 code 含奇怪 unicode），退回纯文本
        try:
            await _send_text(
                bot,
                chat_id=request.applicant_telegram_id,
                text=f"🎁 您的报销已批准并发放！\n金额：{amount_yuan} 元\n\n口令：\n{code}",
            )
        except BadRequest:
            pass

    # 编辑审核消息为"已付款"
    await _edit_audit_messages(
        session, bot,
        reimbursement_id=request.id,
        reviewer_display=reviewer_display,
        reviewer_telegram_id=reviewer_telegram_id,
        marker_text=f"💸 已付款 by {reviewer_display or f'#{reviewer_telegram_id}'}",
    )

    # 日志频道
    try:
        await log_channel_service.push_reimbursement_event(
            session, bot,
            kind="paid",
            reimbursement_id=request.id,
            applicant_telegram_id=request.applicant_telegram_id,
            applicant_username=request.applicant_username,
            amount_cents=request.amount_cents,
            reviewer_telegram_id=reviewer_telegram_id,
            reviewer_display=reviewer_display,
        )
    except Exception:  # noqa: BLE001
        log.exception("rei_log_paid_failed", reimbursement_id=request.id)

    log.info("reimbursement_paid", reimbursement_id=request.id)


# ---------- 拒绝流程 ----------


async def reject_request(
    session: AsyncSession,
    bot: Bot,
    request: ReimbursementRequest,
    *,
    reviewer_telegram_id: int,
    reviewer_display: str | None,
    reason: str | None,
    is_budget_reject: bool = False,
) -> None:
    if request.status not in (REI_STATUS_PENDING, REI_STATUS_APPROVED):
        raise ReimbursementAuditError("该报销已是终态，无法拒绝")

    # 如果之前已 approve 扣过预算，这里要退回（边界场景：是 v3 才考虑；v2 简化忽略）
    request.status = REI_STATUS_REJECTED
    request.reject_reason = reason
    request.reviewed_at = datetime.now(timezone.utc)
    request.reviewed_by_telegram_id = reviewer_telegram_id
    await session.flush()

    session.add(
        AuditLog(
            actor_telegram_id=reviewer_telegram_id,
            actor_role="admin",
            action="reimbursement_reject",
            target_application_id=None,
            details={
                "reimbursement_id": request.id,
                "reason": reason,
                "is_budget_reject": is_budget_reject,
            },
        )
    )

    # 通知申请人
    amount_yuan = reimbursement_settings.cents_to_yuan_display(request.amount_cents)
    reason_line = f"\n原因：{reason}" if reason else ""
    try:
        await _send_text(
            bot,
            chat_id=request.applicant_telegram_id,
            text=f"❌ 您的报销申请未通过。\n金额：{amount_yuan} 元{reason_line}",
        )
    except BadRequest as e:
        log.error("rei_reject_notify_failed", reimbursement_id=request.id, err=str(e))

    # 编辑审核消息
    marker = f"❌ 已拒绝 by {reviewer_display or f'#{reviewer_telegram_id}'}"
    if reason:
        marker += f"\n原因：{reason}"
    await _edit_audit_messages(
        session, bot,
        reimbursement_id=request.id,
        reviewer_display=reviewer_display,
        reviewer_telegram_id=reviewer_telegram_id,
        marker_text=marker,
    )

    # 日志频道
    try:
        kind = "budget_reject" if is_budget_reject else "rejected"
        await log_channel_service.push_reimbursement_event(
            session, bot,
            kind=kind,
            reimbursement_id=request.id,
            applicant_telegram_id=request.applicant_telegram_id,
            applicant_username=request.applicant_username,
            amount_cents=request.amount_cents,
            reviewer_telegram_id=reviewer_telegram_id,
            reviewer_display=reviewer_display,
            reason=reason,
        )
    except Exception:  # noqa: BLE001
        log.exception("rei_log_rejected_failed", reimbursement_id=request.id)


# ---------- 共用：编辑审核消息 ----------


async def _edit_audit_messages(
    session: AsyncSession,
    bot: Bot,
    *,
    reimbursement_id: int,
    reviewer_display: str | None,
    reviewer_telegram_id: int,
    marker_text: str,
) -> None:
    """编辑所有 audit_message 的文本消息为终态文案；非 acting 显示'已被处理'。"""
    result = await session.execute(
        select(ReimbursementAuditMessage).where(
            ReimbursementAuditMessage.reimbursement_id == reimbursement_id
        )
    )
    rows = list(result.scalars().all())
    others_marker = (
        f"⏩ 已被 {reviewer_display or f'#{reviewer_telegram_id}'} 处理"
    )
    for am in rows:
        text = marker_text if am.reviewer_telegram_id == reviewer_telegram_id else others_marker
        try:
            await _edit_text(bot, am.reviewer_telegram_id, am.text_message_id, text)
        except BadRequest as e:
            log.warning(
                "rei_audit_msg_edit_failed",
                reimbursement_id=reimbursement_id,
                reviewer_chat_id=am.reviewer_telegram_id,
                err=str(e),
            )


# ---------- 重发审核材料 ----------


async def repost_materials(
    session: AsyncSession,
    bot: Bot,
    request: ReimbursementRequest,
    *,
    requester_telegram_id: int,
) -> None:
    materials = await reimbursement_repo.list_materials(session, request.id)
    photos, report_text = _split_materials(materials)
    summary = await _build_summary(session, request)
    await _push_to_reviewer(
        session, bot,
        request=request,
        reviewer_chat_id=requester_telegram_id,
        photos=photos,
        report_text=report_text,
        summary_text=summary,
    )
