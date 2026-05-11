"""资格群组/频道列表 CRUD。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.eligibility_chat import EligibilityChat


async def list_active(session: AsyncSession) -> list[EligibilityChat]:
    result = await session.execute(
        select(EligibilityChat).where(EligibilityChat.is_active.is_(True)).order_by(EligibilityChat.id)
    )
    return list(result.scalars().all())


async def list_all(session: AsyncSession) -> list[EligibilityChat]:
    result = await session.execute(select(EligibilityChat).order_by(EligibilityChat.id))
    return list(result.scalars().all())


async def find_by_telegram_chat_id(
    session: AsyncSession, telegram_chat_id: int
) -> EligibilityChat | None:
    result = await session.execute(
        select(EligibilityChat).where(EligibilityChat.telegram_chat_id == telegram_chat_id).limit(1)
    )
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    telegram_chat_id: int,
    chat_type: str,
    name: str,
) -> EligibilityChat:
    e = EligibilityChat(
        telegram_chat_id=telegram_chat_id,
        chat_type=chat_type,
        name=name,
        is_active=True,
    )
    session.add(e)
    await session.flush()
    return e


async def deactivate(session: AsyncSession, e: EligibilityChat) -> None:
    e.is_active = False
    await session.flush()


async def activate(session: AsyncSession, e: EligibilityChat) -> None:
    e.is_active = True
    await session.flush()
