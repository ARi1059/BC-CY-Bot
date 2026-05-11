from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.blacklist import Blacklist


async def is_blacklisted(session: AsyncSession, telegram_user_id: int) -> bool:
    result = await session.execute(
        select(Blacklist.id).where(Blacklist.telegram_user_id == telegram_user_id).limit(1)
    )
    return result.scalar_one_or_none() is not None
