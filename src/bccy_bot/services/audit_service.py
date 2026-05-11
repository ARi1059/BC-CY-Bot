"""
审核流程编排（[REQ §3.2]）。

职责：
- pending 申请到达后路由到审核者（自审型推给邀请人；代审型 M3 接管）
- 推送双消息（媒体组 + caption 报告 / 申请人信息+按钮）
- 通过/拒绝时执行业务动作 + 编辑审核消息为终态
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InputMediaPhoto
from telegram.error import BadRequest

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.application_material import ApplicationMaterial
from bccy_bot.db.models.audit_log import AuditLog
from bccy_bot.db.models.audit_message import AuditMessage
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    APP_STATUS_PENDING,
    APP_STATUS_REJECTED,
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REVIEW_MODE_DELEGATED,
    REVIEW_MODE_SELF,
    REVIEWED_BY_ADMIN,
    REVIEWED_BY_INVITER,
)
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.keyboards.factory import (
    applicant_link_keyboard,
    audit_keyboard,
    reject_choice_keyboard,
)
from bccy_bot.repositories import admin_repo, application_repo, inviter_repo
from bccy_bot.services import (
    attack_report_service,
    invite_link_service,
    log_channel_service,
    recovery_key_service,
)
from bccy_bot.utils.retry import telegram_retry

log = structlog.get_logger()

# Telegram 媒体组 caption 限长（[REQ §3.2.1]）
MEDIA_CAPTION_MAX = 1024


class AuditError(Exception):
    pass


@dataclass
class _AuditPayload:
    photos: list[ApplicationMaterial]  # 按 (约课记录, 上课手势) 顺序
    report_text: str | None
    summary_text: str  # 消息 ② 主体


# ---------- 内部组装 ----------


def _build_summary_text(application: Application, inviter: Inviter | None) -> str:
    inviter_label = (
        f"{inviter.display_name}（{inviter.group_label}）" if inviter else "（未知）"
    )
    submitted_at = (
        application.submitted_at.strftime("%Y-%m-%d %H:%M")
        if application.submitted_at
        else "—"
    )
    username_part = f"@{application.applicant_username}" if application.applicant_username else "（无用户名）"
    return (
        f"📥 新申请待审核 #A{application.id}\n"
        "─────────────────────────\n"
        f"👤 申请人：{username_part}\n"
        f"🆔 ID：{application.applicant_telegram_id}\n"
        f"🎓 邀请人：{inviter_label}\n"
        f"🕐 提交时间：{submitted_at}"
    )


def _split_materials(materials: list[ApplicationMaterial]) -> tuple[list[ApplicationMaterial], str | None]:
    """
    把材料按类型分组：照片（约课记录 + 上课手势，按此顺序）+ 出击报告文本。
    """
    by_type: dict[str, ApplicationMaterial] = {}
    for m in materials:
        by_type[m.material_type] = m

    photos: list[ApplicationMaterial] = []
    for mt in (MAT_BOOKING, MAT_GESTURE):
        m = by_type.get(mt)
        if m is not None and m.content_type == CT_PHOTO and m.telegram_file_id:
            photos.append(m)

    report = by_type.get(MAT_REPORT)
    report_text = report.text_content if report and report.content_type == CT_TEXT else None
    return photos, report_text


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


# ---------- 主入口：推送审核 ----------


async def notify_reviewers(session: AsyncSession, bot: Bot, application: Application) -> None:
    """
    pending 申请触发：根据 inviter.review_mode 路由推送。

    M2 仅支持 self 模式；admin_delegated 留 TODO 给 M3。
    """
    if application.status != APP_STATUS_PENDING:
        return

    if application.inviter_id is None:
        log.warning("notify_reviewers_no_inviter", application_id=application.id)
        return

    inviter = await inviter_repo.get_by_id(session, application.inviter_id)
    if inviter is None:
        log.warning("notify_reviewers_inviter_missing", application_id=application.id)
        return

    materials = await application_repo.list_materials(session, application.id)
    photos, report_text = _split_materials(materials)
    summary = _build_summary_text(application, inviter)

    # 触发日志频道 "📥 新申请" 事件（[REQ §3.6.2]）—— 不阻塞主流程
    try:
        await log_channel_service.push_new_application(session, bot, application)
    except Exception:  # noqa: BLE001
        log.exception("log_channel_new_application_failed", application_id=application.id)

    if inviter.review_mode == REVIEW_MODE_SELF:
        if inviter.telegram_user_id is None:
            log.warning(
                "self_review_inviter_no_tg_id",
                application_id=application.id,
                inviter_id=inviter.id,
            )
            return
        await _push_to_reviewer(
            session,
            bot,
            application=application,
            reviewer_chat_id=inviter.telegram_user_id,
            photos=photos,
            report_text=report_text,
            summary_text=summary,
        )
        return

    if inviter.review_mode == REVIEW_MODE_DELEGATED:
        admins = await admin_repo.list_all(session)
        if not admins:
            log.warning(
                "delegated_review_no_admins",
                application_id=application.id,
                inviter_id=inviter.id,
            )
            return

        for adm in admins:
            try:
                await _push_to_reviewer(
                    session,
                    bot,
                    application=application,
                    reviewer_chat_id=adm.telegram_user_id,
                    photos=photos,
                    report_text=report_text,
                    summary_text=summary,
                )
            except BadRequest as e:
                # 某个管理员阻断了 Bot —— 跳过，其他管理员仍能审核
                log.warning(
                    "delegated_push_failed_for_admin",
                    application_id=application.id,
                    admin_telegram_id=adm.telegram_user_id,
                    err=str(e),
                )
        return


async def _push_to_reviewer(
    session: AsyncSession,
    bot: Bot,
    *,
    application: Application,
    reviewer_chat_id: int,
    photos: list[ApplicationMaterial],
    report_text: str | None,
    summary_text: str,
) -> AuditMessage:
    """
    向单个审核者推送审核材料。

    消息结构（[REQ §3.2.1]）：
    - 有图：媒体组（首图 caption=报告）
      - caption > 1024 → 降级三消息（媒体组 + 独立报告 + 按钮）
    - 无图：直接发文本+按钮（包含报告）
    """
    media_message_id: int | None = None
    report_message_id: int | None = None

    long_report = (report_text is not None and len(report_text) > MEDIA_CAPTION_MAX)

    if photos:
        caption = report_text if (report_text and not long_report) else None
        media = [
            InputMediaPhoto(media=p.telegram_file_id, caption=(caption if i == 0 else None))
            for i, p in enumerate(photos)
        ]
        sent = await _send_media_group(bot, reviewer_chat_id, media)
        if sent:
            media_message_id = sent[0].message_id

        if long_report and report_text:
            sent_report = await _send_text(bot, reviewer_chat_id, f"📝 出击报告：\n{report_text}")
            report_message_id = sent_report.message_id

    elif report_text:
        # 无图，只把报告并入消息 ②（avoid empty media_group）
        summary_text = f"{summary_text}\n\n📝 出击报告：\n{report_text}"

    button_msg = await _send_text(
        bot,
        reviewer_chat_id,
        summary_text,
        reply_markup=audit_keyboard(application.id),
    )

    audit_msg = AuditMessage(
        application_id=application.id,
        reviewer_telegram_id=reviewer_chat_id,
        media_message_id=media_message_id,
        text_message_id=button_msg.message_id,
        report_message_id=report_message_id,
    )
    session.add(audit_msg)
    await session.flush()

    log.info(
        "audit_pushed",
        application_id=application.id,
        reviewer_chat_id=reviewer_chat_id,
        has_media=media_message_id is not None,
        long_report=long_report,
    )
    return audit_msg


# ---------- 审核动作：通过 ----------


@dataclass
class ApprovalResult:
    invite_link_url: str
    recovery_key_plaintext: str | None  # 首次签发才有，重新审核时为 None


async def approve_application(
    session: AsyncSession,
    bot: Bot,
    application: Application,
    *,
    reviewer_telegram_id: int,
    reviewer_role: str,  # 'inviter' or 'admin'
    reviewer_display: str | None = None,
) -> ApprovalResult:
    if application.status != APP_STATUS_PENDING:
        raise AuditError("该申请已不在待审核状态")

    # 1. 生成链接（落库）
    db_link = await invite_link_service.create_one_time_link(session, bot, application)

    # 2. 签发回群密钥（首次通过才签）
    key_result = await recovery_key_service.issue_first_key(session, application)
    key_plaintext = key_result[1] if key_result else None

    # 3. 状态机
    application.status = APP_STATUS_APPROVED
    application.reviewed_at = datetime.now(timezone.utc)
    application.reviewed_by_type = (
        REVIEWED_BY_INVITER if reviewer_role == "inviter" else REVIEWED_BY_ADMIN
    )
    application.reviewed_by_id = reviewer_telegram_id
    await session.flush()

    session.add(
        AuditLog(
            actor_telegram_id=reviewer_telegram_id,
            actor_role=reviewer_role,
            action="approve",
            target_application_id=application.id,
            details={"invite_link_id": db_link.id, "ttl_hours_used": None},
        )
    )

    # 4. 私聊申请人（链接 + 密钥卡片）
    await _send_approval_to_applicant(
        bot,
        applicant_telegram_id=application.applicant_telegram_id,
        invite_link_url=db_link.invite_link,
        recovery_key_plaintext=key_plaintext,
    )

    # 5. 编辑所有审核消息 ② 为"已通过"
    await _edit_audit_messages(
        session,
        bot,
        application_id=application.id,
        reviewer_display=reviewer_display,
        reviewer_telegram_id=reviewer_telegram_id,
        is_approved=True,
    )

    # 6. 日志频道：✅ 审核通过
    try:
        await log_channel_service.push_approval(
            session,
            bot,
            application,
            reviewer_telegram_id=reviewer_telegram_id,
            reviewer_role=reviewer_role,
            reviewer_display=reviewer_display,
            invite_link_url=db_link.invite_link,
        )
    except Exception:  # noqa: BLE001
        log.exception("log_channel_approval_failed", application_id=application.id)

    # 7. 出击报告频道：仅当含 MAT_REPORT 材料 + 频道已配置时转发
    try:
        await attack_report_service.forward_report(session, bot, application)
    except Exception:  # noqa: BLE001
        log.exception("attack_report_forward_failed_outer", application_id=application.id)

    log.info(
        "application_approved",
        application_id=application.id,
        reviewer_id=reviewer_telegram_id,
        reviewer_role=reviewer_role,
    )
    return ApprovalResult(
        invite_link_url=db_link.invite_link,
        recovery_key_plaintext=key_plaintext,
    )


async def _send_approval_to_applicant(
    bot: Bot,
    *,
    applicant_telegram_id: int,
    invite_link_url: str,
    recovery_key_plaintext: str | None,
) -> None:
    lines = [
        "🎉 您的入群申请已通过！",
        "⚠️ 此链接仅可使用 1 次，请勿转发。",
    ]
    if recovery_key_plaintext is not None:
        lines.append("")
        lines.append("🔑 您的回群密钥（请妥善保存）：")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(recovery_key_plaintext)
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 若日后账号丢失/封禁，可用新账号")
        lines.append("   向 Bot 发送此密钥重新获取入群链接")
    text = "\n".join(lines)
    try:
        await _send_text(
            bot,
            chat_id=applicant_telegram_id,
            text=text,
            reply_markup=applicant_link_keyboard(invite_link_url),
        )
    except BadRequest as e:
        log.error(
            "applicant_notify_failed",
            applicant_telegram_id=applicant_telegram_id,
            err=str(e),
        )


# ---------- 审核动作：拒绝 ----------


async def reject_application(
    session: AsyncSession,
    bot: Bot,
    application: Application,
    *,
    reviewer_telegram_id: int,
    reviewer_role: str,
    reason: str | None,
    reviewer_display: str | None = None,
) -> None:
    if application.status != APP_STATUS_PENDING:
        raise AuditError("该申请已不在待审核状态")

    application.status = APP_STATUS_REJECTED
    application.reject_reason = reason
    application.reviewed_at = datetime.now(timezone.utc)
    application.reviewed_by_type = (
        REVIEWED_BY_INVITER if reviewer_role == "inviter" else REVIEWED_BY_ADMIN
    )
    application.reviewed_by_id = reviewer_telegram_id
    await session.flush()

    session.add(
        AuditLog(
            actor_telegram_id=reviewer_telegram_id,
            actor_role=reviewer_role,
            action="reject",
            target_application_id=application.id,
            details={"reason": reason},
        )
    )

    await _send_rejection_to_applicant(
        bot,
        applicant_telegram_id=application.applicant_telegram_id,
        reason=reason,
    )

    await _edit_audit_messages(
        session,
        bot,
        application_id=application.id,
        reviewer_display=reviewer_display,
        reviewer_telegram_id=reviewer_telegram_id,
        is_approved=False,
        reject_reason=reason,
    )

    # 日志频道：❌ 审核拒绝
    try:
        await log_channel_service.push_rejection(
            session,
            bot,
            application,
            reviewer_telegram_id=reviewer_telegram_id,
            reviewer_role=reviewer_role,
            reviewer_display=reviewer_display,
            reason=reason,
        )
    except Exception:  # noqa: BLE001
        log.exception("log_channel_rejection_failed", application_id=application.id)

    log.info(
        "application_rejected",
        application_id=application.id,
        reviewer_id=reviewer_telegram_id,
        has_reason=reason is not None,
    )


async def _send_rejection_to_applicant(
    bot: Bot,
    *,
    applicant_telegram_id: int,
    reason: str | None,
) -> None:
    lines = ["❌ 您的申请未通过。"]
    if reason:
        lines.append("")
        lines.append(f"原因：{reason}")
    else:
        lines.append("")
        lines.append("如需了解原因，请联系审核人或管理员。")
    try:
        await _send_text(
            bot,
            chat_id=applicant_telegram_id,
            text="\n".join(lines),
        )
    except BadRequest as e:
        log.error(
            "applicant_reject_notify_failed",
            applicant_telegram_id=applicant_telegram_id,
            err=str(e),
        )


# ---------- 公共：编辑审核消息为终态 ----------


async def _edit_audit_messages(
    session: AsyncSession,
    bot: Bot,
    *,
    application_id: int,
    reviewer_display: str | None,
    reviewer_telegram_id: int,
    is_approved: bool,
    reject_reason: str | None = None,
) -> None:
    """
    审核终态时编辑所有审核消息 ②：
    - 真正操作的审核者（acting）那条 → 「✅ 已通过 by @xxx · HH:MM」
    - 其他审核者（代审型多管理员） → 「⏩ 已被 @xxx 处理」
    """
    result = await session.execute(
        select(AuditMessage).where(AuditMessage.application_id == application_id)
    )
    audit_messages = list(result.scalars().all())

    now = datetime.now(timezone.utc).strftime("%H:%M")
    actor = reviewer_display or f"#{reviewer_telegram_id}"

    if is_approved:
        acting_marker = f"✅ 已通过 by {actor} · {now}"
    else:
        acting_marker = f"❌ 已拒绝 by {actor} · {now}"
        if reject_reason:
            acting_marker += f"\n原因：{reject_reason}"

    others_marker = f"⏩ 已被 {actor} 处理 · {now}"

    for am in audit_messages:
        is_acting = am.reviewer_telegram_id == reviewer_telegram_id
        text = acting_marker if is_acting else others_marker
        try:
            await _edit_text(bot, am.reviewer_telegram_id, am.text_message_id, text)
        except BadRequest as e:
            log.warning(
                "audit_msg_edit_failed",
                application_id=application_id,
                reviewer_chat_id=am.reviewer_telegram_id,
                msg_id=am.text_message_id,
                err=str(e),
            )


# ---------- 重发审核材料（用户点 [👁 重发审核材料]） ----------


async def repost_materials(
    session: AsyncSession,
    bot: Bot,
    application: Application,
    *,
    requester_telegram_id: int,
) -> None:
    """重新把媒体组+报告推送到请求者，避免被新消息淹没。"""
    materials = await application_repo.list_materials(session, application.id)
    photos, report_text = _split_materials(materials)
    inviter = (
        await inviter_repo.get_by_id(session, application.inviter_id)
        if application.inviter_id
        else None
    )
    summary = _build_summary_text(application, inviter)
    await _push_to_reviewer(
        session,
        bot,
        application=application,
        reviewer_chat_id=requester_telegram_id,
        photos=photos,
        report_text=report_text,
        summary_text=summary,
    )
