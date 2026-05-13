"""
链接使用追踪 + 过期扫描（[REQ §3.5]）。

输入来源：
- chat_member 事件（用户实际入群）
- 定时任务（每小时扫一遍未用且已过期的链接）

写日志的事件类型（M6 接日志频道前先打 structlog）：
- invite_link_used: 正常入群
- invite_link_anomaly: 入群者 ID ≠ 申请人 ID
- invite_link_expired: 链接 24h 未用，自动标记
"""

from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.repositories import invite_link_repo, recovery_key_repo
from bccy_bot.services import log_channel_service

log = structlog.get_logger()


async def on_member_joined(
    session: AsyncSession,
    *,
    invite_link_name: str,
    joined_user_id: int,
    chat_telegram_id: int | None = None,
    bot: Bot | None = None,
    joined_username: str | None = None,
) -> InviteLink | None:
    """
    chat_member 事件分发入口。

    - 通过 invite_link.name='App-{id}' 反查链接
    - 写入 is_used / used_by_telegram_id / used_at / is_anomaly
    - 异常入群（实际入群者 ID ≠ 申请人 ID）标记 is_anomaly=true
    """
    link = await invite_link_repo.find_active_by_name(session, invite_link_name)
    if link is None:
        log.warning(
            "invite_link_used_unknown_name",
            name=invite_link_name,
            joined_user_id=joined_user_id,
            chat_telegram_id=chat_telegram_id,
        )
        return None

    if link.is_used:
        # 理论上 find_active_by_name 已经过滤；走到这里说明并发竞态，避免重复处理
        log.info(
            "invite_link_already_used_race",
            link_id=link.id,
            link_name=invite_link_name,
        )
        return link

    app = await session.get(Application, link.application_id)

    # 回群密钥救济：若申请下存在 status=used 且 used_by=本人 的密钥，则此次入群是
    # 凭密钥换链接后的回群，应归类为「用户回群」而非「异常入群」。
    recovery_key = None
    if app is not None:
        recovery_key = await recovery_key_repo.find_used_for_app_and_claimer(
            session,
            application_id=link.application_id,
            claimer_telegram_id=joined_user_id,
        )

    is_recovery_rejoin = recovery_key is not None
    is_anomaly = (
        not is_recovery_rejoin
        and app is not None
        and joined_user_id != app.applicant_telegram_id
    )

    link.is_used = True
    link.used_by_telegram_id = joined_user_id
    link.used_at = datetime.now(timezone.utc)
    link.is_anomaly = is_anomaly
    await session.flush()

    if is_recovery_rejoin:
        log.info(
            "invite_link_used_recovery_rejoin",
            link_id=link.id,
            link_name=invite_link_name,
            application_id=link.application_id,
            joined_user_id=joined_user_id,
            recovery_key_id=recovery_key.id if recovery_key else None,
        )
    elif is_anomaly:
        log.warning(
            "invite_link_anomaly",
            link_id=link.id,
            link_name=invite_link_name,
            application_id=link.application_id,
            applicant_telegram_id=app.applicant_telegram_id if app else None,
            joined_user_id=joined_user_id,
        )
    else:
        log.info(
            "invite_link_used",
            link_id=link.id,
            link_name=invite_link_name,
            application_id=link.application_id,
            joined_user_id=joined_user_id,
        )

    # 日志频道推送（[REQ §3.6.2]）：失败不阻塞主流程
    if bot is not None:
        try:
            if is_recovery_rejoin:
                await log_channel_service.push_user_rejoined(
                    session, bot, app, link,
                    joined_user_id=joined_user_id,
                    joined_username=joined_username,
                    recovery_key=recovery_key,
                )
            elif is_anomaly:
                await log_channel_service.push_anomaly(
                    session, bot, app, link,
                    joined_user_id=joined_user_id, joined_username=joined_username,
                )
            else:
                await log_channel_service.push_link_used(
                    session, bot, app, link,
                    joined_user_id=joined_user_id, joined_username=joined_username,
                )
        except Exception:  # noqa: BLE001
            log.exception("log_channel_link_used_failed", link_id=link.id)

    return link


async def sweep_expired(session: AsyncSession, bot: Bot | None = None) -> list[InviteLink]:
    """
    定时任务：标记 24h 未用的过期链接 + 推送日志频道告警。

    返回本轮新标记为 expired 的链接列表。
    """
    expired = await invite_link_repo.list_newly_expired(session)
    if not expired:
        return []

    now = datetime.now(timezone.utc)
    for link in expired:
        link.expired_notified_at = now
        log.info(
            "invite_link_expired",
            link_id=link.id,
            link_name=link.invite_link_name,
            application_id=link.application_id,
            expire_date=link.expire_date.isoformat() if link.expire_date else None,
        )
        if bot is not None:
            try:
                await log_channel_service.push_link_expired(session, bot, link)
            except Exception:  # noqa: BLE001
                log.exception("log_channel_expired_failed", link_id=link.id)
    await session.flush()
    return expired
