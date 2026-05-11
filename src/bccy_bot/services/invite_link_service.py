"""一次性入群邀请链接的生成与持久化。"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import SK_INVITE_LINK_TTL_HOURS
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.repositories import inviter_repo, settings_repo
from bccy_bot.utils.retry import telegram_retry

log = structlog.get_logger()

DEFAULT_TTL_HOURS = 24
MIN_TTL_HOURS = 1
MAX_TTL_HOURS = 168


async def get_link_ttl_hours(session: AsyncSession) -> int:
    """读取 invite_link_ttl_hours 配置，默认 24，clamp 到 [1, 168]。"""
    h = await settings_repo.get_int(session, SK_INVITE_LINK_TTL_HOURS, DEFAULT_TTL_HOURS)
    return max(MIN_TTL_HOURS, min(MAX_TTL_HOURS, h))


@telegram_retry(max_attempts=3)
async def _call_create_invite_link(
    bot: Bot,
    *,
    chat_id: int,
    expire_date: datetime,
    name: str,
):
    return await bot.create_chat_invite_link(
        chat_id=chat_id,
        member_limit=1,
        expire_date=expire_date,
        name=name,
        creates_join_request=False,
    )


async def create_one_time_link(
    session: AsyncSession,
    bot: Bot,
    application: Application,
) -> InviteLink:
    """生成一次性入群链接并落库。"""
    if application.inviter_id is None:
        raise ValueError("application has no inviter, cannot create invite link")

    inviter: Inviter | None = await inviter_repo.get_by_id(session, application.inviter_id)
    if inviter is None:
        raise ValueError("inviter not found")

    target_group_id = inviter.target_group_id
    from bccy_bot.db.models.group import Group
    group = await session.get(Group, target_group_id)
    if group is None:
        raise ValueError("target group not found")

    ttl_hours = await get_link_ttl_hours(session)
    expire_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    name = f"App-{application.id}"

    tg_link = await _call_create_invite_link(
        bot,
        chat_id=group.telegram_chat_id,
        expire_date=expire_at,
        name=name,
    )

    db_link = InviteLink(
        application_id=application.id,
        invite_link=tg_link.invite_link,
        invite_link_name=name,
        group_id=group.id,
        expire_date=expire_at,
        is_used=False,
        is_anomaly=False,
    )
    session.add(db_link)
    await session.flush()

    log.info(
        "invite_link_created",
        application_id=application.id,
        invite_link_id=db_link.id,
        ttl_hours=ttl_hours,
    )
    return db_link
