"""
日志频道推送（[REQ §3.6]）。

事件卡片（每条以 hashtag 标签开头，便于在 Telegram 搜索追溯）：
- 📥 新申请        → audit_service.notify_reviewers          → #新的群审核 #邀请人
- ✅ 审核通过      → audit_service.approve_application       → #审核通过 #邀请人
- ❌ 审核拒绝      → audit_service.reject_application        → #审核拒绝 #邀请人
- 🚪 链接已使用    → link_tracking_service.on_member_joined  → #用户加入群组 #邀请人
- 👤 用户回群      → link_tracking_service.on_member_joined  → #用户回群 #邀请人
- ⚠️ 异常入群      → link_tracking_service                   → #异常入群告警 #邀请人
- 🔑 回群密钥使用  → recovery_key_service.verify_and_consume → #回群密钥使用 #邀请人
- ⚠️ 密钥使用异常  → recovery_key_service                    → #密钥使用异常
- ⏰ 链接过期未用  → link_tracking_service.sweep_expired     → #链接过期
- 💰 报销 5 状态   → reimbursement_audit_service             → #报销申请 / #报销审核通过 / #报销完成 / #报销拒绝 / #报销预算不足 + #报销人

频道未配置时静默跳过；推送失败不阻塞主流程。
"""

from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import BadRequest

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import SK_LOG_CHANNEL_ID
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.db.models.recovery_key import RecoveryKey
from bccy_bot.repositories import inviter_repo, settings_repo
from bccy_bot.utils.retry import telegram_retry

log = structlog.get_logger()


# ---------- 通用工具 ----------


async def _get_channel_id(session: AsyncSession) -> int | None:
    val = await settings_repo.get(session, SK_LOG_CHANNEL_ID)
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        log.warning("log_channel_id_malformed", value=val)
        return None


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _tags(*tags: str) -> str:
    """格式化 hashtag 块作为消息首行，便于 Telegram 内搜索归类。"""
    return " ".join(tags)


def _applicant_label(application: Application) -> str:
    name = f"@{application.applicant_username}" if application.applicant_username else "（无用户名）"
    return f"{name} ({application.applicant_telegram_id})"


def _inviter_label(inviter: Inviter | None) -> str:
    if inviter is None:
        return "（未知）"
    return inviter.display_name


def _user_label(telegram_id: int, username: str | None) -> str:
    name = f"@{username}" if username else "（无用户名）"
    return f"{name} ({telegram_id})"


def _mask_link(url: str) -> str:
    """t.me/+ABCDEF1234567 → t.me/+ABCD****"""
    if "+" not in url:
        return url
    prefix, code = url.split("+", 1)
    if len(code) <= 4:
        return url
    return f"{prefix}+{code[:4]}****"


@telegram_retry(max_attempts=3)
async def _send(bot: Bot, chat_id: int, text: str) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        disable_notification=True,
        disable_web_page_preview=True,
    )


async def _safe_push(session: AsyncSession, bot: Bot, *, text: str, kind: str) -> bool:
    """读取频道配置 → 发送（失败仅 log，不抛）。返回是否真的发出去了。"""
    channel_id = await _get_channel_id(session)
    if channel_id is None:
        log.info("log_channel_unconfigured", kind=kind)
        return False
    try:
        await _send(bot, channel_id, text)
        return True
    except BadRequest as e:
        log.error("log_channel_push_failed", kind=kind, channel_id=channel_id, err=str(e))
        return False
    except Exception:  # noqa: BLE001
        log.exception("log_channel_push_unexpected", kind=kind, channel_id=channel_id)
        return False


# ---------- 事件 ----------


async def push_new_application(
    session: AsyncSession, bot: Bot, application: Application
) -> None:
    inv = await inviter_repo.get_by_id(session, application.inviter_id) if application.inviter_id else None
    submitted = (
        application.submitted_at.strftime("%Y-%m-%d %H:%M")
        if application.submitted_at
        else _now_str()
    )
    display = application.applicant_display_name or "（未填）"
    text = (
        f"{_tags('#新的群审核', '#邀请人')}\n"
        f"📥 新申请待审核 #A{application.id}\n"
        "─────────────────────────\n"
        f"👤 申请人：{_applicant_label(application)}\n"
        f"📛 显示名：{display}\n"
        f"🎓 邀请人：{_inviter_label(inv)}\n"
        f"🕐 提交时间：{submitted}"
    )
    await _safe_push(session, bot, text=text, kind="new_application")


async def push_approval(
    session: AsyncSession,
    bot: Bot,
    application: Application,
    *,
    reviewer_telegram_id: int,
    reviewer_role: str,  # 'inviter' or 'admin'
    reviewer_display: str | None,
    invite_link_url: str,
) -> None:
    inv = await inviter_repo.get_by_id(session, application.inviter_id) if application.inviter_id else None
    actor = reviewer_display or f"#{reviewer_telegram_id}"
    role_label = "邀请人" if reviewer_role == "inviter" else "管理员"
    display = application.applicant_display_name or "（未填）"
    text = (
        f"{_tags('#审核通过', '#邀请人')}\n"
        f"✅ 审核通过 #A{application.id}\n"
        "─────────────────────────\n"
        f"👤 申请人：{_applicant_label(application)}\n"
        f"📛 显示名：{display}\n"
        f"🎓 邀请人：{_inviter_label(inv)}\n"
        f"👮 审核人：{role_label} {actor} (ID {reviewer_telegram_id})\n"
        f"🕐 时间：{_now_str()}\n"
        f"🔗 链接：{_mask_link(invite_link_url)}"
    )
    await _safe_push(session, bot, text=text, kind="approval")


async def push_rejection(
    session: AsyncSession,
    bot: Bot,
    application: Application,
    *,
    reviewer_telegram_id: int,
    reviewer_role: str,
    reviewer_display: str | None,
    reason: str | None,
) -> None:
    inv = await inviter_repo.get_by_id(session, application.inviter_id) if application.inviter_id else None
    actor = reviewer_display or f"#{reviewer_telegram_id}"
    role_label = "邀请人" if reviewer_role == "inviter" else "管理员"
    reason_line = reason if reason else "（未填写）"
    display = application.applicant_display_name or "（未填）"
    text = (
        f"{_tags('#审核拒绝', '#邀请人')}\n"
        f"❌ 审核拒绝 #A{application.id}\n"
        "─────────────────────────\n"
        f"👤 申请人：{_applicant_label(application)}\n"
        f"📛 显示名：{display}\n"
        f"🎓 邀请人：{_inviter_label(inv)}\n"
        f"👮 审核人：{role_label} {actor} (ID {reviewer_telegram_id})\n"
        f"💬 原因：{reason_line}\n"
        f"🕐 时间：{_now_str()}"
    )
    await _safe_push(session, bot, text=text, kind="rejection")


async def push_link_used(
    session: AsyncSession,
    bot: Bot,
    application: Application | None,
    link: InviteLink,
    *,
    joined_user_id: int,
    joined_username: str | None = None,
) -> None:
    """正常入群路径（申请人 ID == 入群 ID，且非回群密钥救济）。"""
    inv = None
    if application is not None and application.inviter_id is not None:
        inv = await inviter_repo.get_by_id(session, application.inviter_id)
    applicant = _applicant_label(application) if application is not None else f"({joined_user_id})"
    joined_label = _user_label(joined_user_id, joined_username)
    created = (
        link.created_at.strftime("%Y-%m-%d %H:%M")
        if link.created_at
        else "—"
    )
    text = (
        f"{_tags('#用户加入群组', '#邀请人')}\n"
        f"🚪 链接已使用 #A{link.application_id}\n"
        "─────────────────────────\n"
        f"👤 申请人：{applicant}\n"
        f"🎓 邀请人：{_inviter_label(inv)}\n"
        f"🚪 实际入群人：{joined_label}  ✓ 一致\n"
        f"🔗 链接：{_mask_link(link.invite_link)}\n"
        f"📅 颁发时间：{created}\n"
        f"🕐 入群时间：{_now_str()}"
    )
    await _safe_push(session, bot, text=text, kind="link_used")


async def push_user_rejoined(
    session: AsyncSession,
    bot: Bot,
    application: Application | None,
    link: InviteLink,
    *,
    joined_user_id: int,
    joined_username: str | None = None,
    recovery_key: RecoveryKey | None = None,
) -> None:
    """回群密钥救济场景：旧账号丢失后凭密钥换新链接入群。"""
    inv = None
    if application is not None and application.inviter_id is not None:
        inv = await inviter_repo.get_by_id(session, application.inviter_id)
    joined_label = _user_label(joined_user_id, joined_username)
    original_id = recovery_key.original_owner_telegram_id if recovery_key else None
    cleanup = recovery_key.cleanup_action if recovery_key else "—"
    cleanup_status = recovery_key.cleanup_old_account_status if recovery_key else "—"
    used_at = (
        recovery_key.used_at.strftime("%Y-%m-%d %H:%M")
        if (recovery_key and recovery_key.used_at)
        else "—"
    )

    lines = [
        f"{_tags('#用户回群', '#邀请人')}",
        f"👤 用户回群 #A{link.application_id}",
        "─────────────────────────",
        f"👤 新账号：{joined_label}",
    ]
    if original_id is not None:
        lines.append(f"📜 原始申请人 ID：{original_id}（已迁移到新账号）")
    lines.extend(
        [
            f"🎓 邀请人：{_inviter_label(inv)}",
            f"🔑 密钥使用时间：{used_at}",
            f"🧹 原账号清理：{cleanup} / 状态：{cleanup_status}",
            f"🔗 链接：{_mask_link(link.invite_link)}",
            f"🕐 入群时间：{_now_str()}",
            "ℹ️ 此次入群通过回群密钥救济通道完成，非首次入群；申请记录已更新为新账号。",
        ]
    )
    await _safe_push(session, bot, text="\n".join(lines), kind="user_rejoined")


async def push_anomaly(
    session: AsyncSession,
    bot: Bot,
    application: Application | None,
    link: InviteLink,
    *,
    joined_user_id: int,
    joined_username: str | None = None,
) -> None:
    """异常入群（实际入群者 ID ≠ 申请人 ID 且非回群密钥救济）。"""
    inv = None
    if application is not None and application.inviter_id is not None:
        inv = await inviter_repo.get_by_id(session, application.inviter_id)
    applicant = _applicant_label(application) if application is not None else "（未知）"
    joined_label = _user_label(joined_user_id, joined_username)
    text = (
        f"{_tags('#异常入群告警', '#邀请人')}\n"
        f"⚠️ 异常告警 #A{link.application_id}\n"
        "─────────────────────────\n"
        f"👤 申请人：{applicant}\n"
        f"🎓 邀请人：{_inviter_label(inv)}\n"
        f"🚪 实际入群人：{joined_label}  ✗ 不一致！\n"
        f"🔗 链接：{_mask_link(link.invite_link)}\n"
        f"🕐 时间：{_now_str()}\n"
        f"建议：核实并考虑加入黑名单"
    )
    await _safe_push(session, bot, text=text, kind="anomaly_join")


async def push_recovery_key_used(
    session: AsyncSession,
    bot: Bot,
    *,
    application: Application,
    old_owner_telegram_id: int,
    new_owner_telegram_id: int,
    new_owner_username: str | None,
    invite_link_url: str,
    cleanup_summary: str,
    old_account_status: str,
) -> None:
    """🔑 回群密钥使用 卡片（[REQ §3.8.6]）。"""
    inv = await inviter_repo.get_by_id(session, application.inviter_id) if application.inviter_id else None
    new_label = _user_label(new_owner_telegram_id, new_owner_username)
    text = (
        f"{_tags('#回群密钥使用', '#邀请人')}\n"
        f"🔑 回群密钥使用 #A{application.id}\n"
        "─────────────────────────\n"
        f"🎓 邀请人：{_inviter_label(inv)}\n"
        f"👤 原账号 ID：{old_owner_telegram_id} · 状态：{old_account_status}\n"
        f"🚀 新账号：{new_label}\n"
        f"🔗 新链接：{_mask_link(invite_link_url)}\n"
        f"🧹 清理动作：{cleanup_summary}\n"
        f"🕐 时间：{_now_str()}\n"
        "ℹ️ 申请记录的当前持有人已更新为新账号；待新账号实际入群时会推送「#用户回群」事件。"
    )
    await _safe_push(session, bot, text=text, kind="recovery_key_used")


async def push_recovery_key_anomaly(
    session: AsyncSession,
    bot: Bot,
    *,
    claimer_telegram_id: int,
    reason: str,
) -> None:
    """⚠️ 密钥使用异常（同 ID 拦截 / 频率锁触发等）。"""
    text = (
        f"{_tags('#密钥使用异常')}\n"
        f"⚠️ 密钥使用异常\n"
        "─────────────────────────\n"
        f"尝试者：({claimer_telegram_id})\n"
        f"原因：{reason}\n"
        f"🕐 时间：{_now_str()}"
    )
    await _safe_push(session, bot, text=text, kind="recovery_key_anomaly")


async def push_reimbursement_event(
    session: AsyncSession,
    bot: Bot,
    *,
    kind: str,  # 'new' | 'approved' | 'paid' | 'rejected' | 'budget_reject'
    reimbursement_id: int,
    applicant_telegram_id: int,
    applicant_username: str | None,
    amount_cents: int,
    reviewer_telegram_id: int | None = None,
    reviewer_display: str | None = None,
    reason: str | None = None,
    teacher_username: str | None = None,
) -> None:
    """报销系统事件推送（[REQ §8.5]）。

    口令红包文本永远不进入日志频道（敏感数据，仅审核者↔申请人私聊可见）。
    """
    user_label = _user_label(applicant_telegram_id, applicant_username)
    amount_yuan = f"{amount_cents / 100:.2f}"
    actor = reviewer_display or (f"#{reviewer_telegram_id}" if reviewer_telegram_id else "?")
    teacher_line = (
        f"\n👨‍🏫 报销老师：@{teacher_username}"
        if teacher_username
        else ""
    )

    if kind == "new":
        text = (
            f"{_tags('#报销申请', '#报销人')}\n"
            f"💰 新报销申请 #R{reimbursement_id}\n"
            "─────────────────────────\n"
            f"👤 申请人：{user_label}{teacher_line}\n"
            f"💵 金额：{amount_yuan} 元\n"
            f"🕐 时间：{_now_str()}"
        )
    elif kind == "approved":
        text = (
            f"{_tags('#报销审核通过', '#报销人')}\n"
            f"✅ 报销已批准 #R{reimbursement_id}\n"
            "─────────────────────────\n"
            f"👤 申请人：{user_label}{teacher_line}\n"
            f"💵 金额：{amount_yuan} 元\n"
            f"👮 审核人：{actor}"
            + (f" (ID {reviewer_telegram_id})" if reviewer_telegram_id else "")
            + f"\n🕐 时间：{_now_str()}\n"
            "等待审核人或口令发放员发送口令红包文本…"
        )
    elif kind == "paid":
        text = (
            f"{_tags('#报销完成', '#报销人')}\n"
            f"💸 报销已发放 #R{reimbursement_id}\n"
            "─────────────────────────\n"
            f"👤 申请人：{user_label}{teacher_line}\n"
            f"💵 金额：{amount_yuan} 元\n"
            f"👮 操作人：{actor}"
            + (f" (ID {reviewer_telegram_id})" if reviewer_telegram_id else "")
            + f"\n🕐 时间：{_now_str()}\n"
            "（口令文本永不进入日志频道）"
        )
    elif kind == "rejected":
        reason_line = reason if reason else "（未填写）"
        text = (
            f"{_tags('#报销拒绝', '#报销人')}\n"
            f"❌ 报销拒绝 #R{reimbursement_id}\n"
            "─────────────────────────\n"
            f"👤 申请人：{user_label}{teacher_line}\n"
            f"💵 金额：{amount_yuan} 元\n"
            f"👮 审核人：{actor}"
            + (f" (ID {reviewer_telegram_id})" if reviewer_telegram_id else "")
            + f"\n💬 原因：{reason_line}\n"
            f"🕐 时间：{_now_str()}"
        )
    elif kind == "budget_reject":
        text = (
            f"{_tags('#报销预算不足', '#报销人')}\n"
            f"⚠️ 报销被退回（预算不足）#R{reimbursement_id}\n"
            "─────────────────────────\n"
            f"👤 申请人：{user_label}{teacher_line}\n"
            f"💵 金额：{amount_yuan} 元\n"
            f"👮 审核人：{actor}"
            + (f" (ID {reviewer_telegram_id})" if reviewer_telegram_id else "")
            + f"\n🕐 时间：{_now_str()}"
        )
    else:
        log.warning("log_channel_unknown_rei_event", kind=kind)
        return

    await _safe_push(session, bot, text=text, kind=f"reimbursement_{kind}")


async def push_link_expired(
    session: AsyncSession,
    bot: Bot,
    link: InviteLink,
) -> None:
    """链接 24h 未用过期告警。"""
    expire = link.expire_date.strftime("%Y-%m-%d %H:%M") if link.expire_date else "—"
    text = (
        f"{_tags('#链接过期')}\n"
        f"⏰ 链接过期未用 #A{link.application_id}\n"
        "─────────────────────────\n"
        f"🔗 链接名：{link.invite_link_name}\n"
        f"📅 失效时间：{expire}\n"
        f"建议：用户须重新申请"
    )
    await _safe_push(session, bot, text=text, kind="link_expired")
