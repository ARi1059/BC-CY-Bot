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

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.repositories import invite_link_repo

log = structlog.get_logger()


async def on_member_joined(
    session: AsyncSession,
    *,
    invite_link_name: str,
    joined_user_id: int,
    chat_telegram_id: int | None = None,
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
    is_anomaly = (app is not None and joined_user_id != app.applicant_telegram_id)

    link.is_used = True
    link.used_by_telegram_id = joined_user_id
    link.used_at = datetime.now(timezone.utc)
    link.is_anomaly = is_anomaly
    await session.flush()

    if is_anomaly:
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

    # TODO(M6): push to log channel: 🚪 链接已使用 / ⚠️ 异常告警

    return link


async def sweep_expired(session: AsyncSession) -> list[InviteLink]:
    """
    定时任务：标记 24h 未用的过期链接 + 推送日志频道（M6 接入前仅 structlog 占位）。

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
        # TODO(M6): push to log channel: ⚠️ 链接过期未用
    await session.flush()
    return expired
