from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.blacklist import Blacklist


async def is_blacklisted(session: AsyncSession, telegram_user_id: int) -> bool:
    result = await session.execute(
        select(Blacklist.id).where(Blacklist.telegram_user_id == telegram_user_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def list_all(session: AsyncSession) -> list[Blacklist]:
    result = await session.execute(select(Blacklist).order_by(Blacklist.id.desc()))
    return list(result.scalars().all())


async def find_by_telegram_user_id(session: AsyncSession, telegram_user_id: int) -> Blacklist | None:
    result = await session.execute(
        select(Blacklist).where(Blacklist.telegram_user_id == telegram_user_id).limit(1)
    )
    return result.scalar_one_or_none()


async def add(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    reason: str | None,
    added_by: int | None,
) -> Blacklist:
    bl = Blacklist(telegram_user_id=telegram_user_id, reason=reason, added_by=added_by)
    session.add(bl)
    await session.flush()
    return bl


async def remove(session: AsyncSession, blacklist: Blacklist) -> None:
    await session.delete(blacklist)
    await session.flush()
