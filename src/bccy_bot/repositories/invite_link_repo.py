from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.invite_link import InviteLink


async def find_active_by_name(session: AsyncSession, name: str) -> InviteLink | None:
    """根据 invite_link_name（如 'App-123'）找到尚未使用的链接。"""
    result = await session.execute(
        select(InviteLink)
        .where(InviteLink.invite_link_name == name, InviteLink.is_used.is_(False))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_newly_expired(session: AsyncSession, *, now: datetime | None = None) -> list[InviteLink]:
    """
    定时扫描需要触发"过期未用"告警的链接：
    - is_used = False
    - expire_date < now
    - expired_notified_at IS NULL（避免重复推送）
    """
    cutoff = now or datetime.now(timezone.utc)
    result = await session.execute(
        select(InviteLink).where(
            InviteLink.is_used.is_(False),
            InviteLink.expire_date < cutoff,
            InviteLink.expired_notified_at.is_(None),
        )
    )
    return list(result.scalars().all())
