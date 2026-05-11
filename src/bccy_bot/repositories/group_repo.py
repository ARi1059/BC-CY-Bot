from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.group import Group


async def list_active(session: AsyncSession) -> list[Group]:
    result = await session.execute(
        select(Group).where(Group.is_active.is_(True)).order_by(Group.id)
    )
    return list(result.scalars().all())


async def list_all(session: AsyncSession) -> list[Group]:
    result = await session.execute(select(Group).order_by(Group.id))
    return list(result.scalars().all())


async def find_by_telegram_chat_id(session: AsyncSession, telegram_chat_id: int) -> Group | None:
    result = await session.execute(
        select(Group).where(Group.telegram_chat_id == telegram_chat_id).limit(1)
    )
    return result.scalar_one_or_none()


async def create(session: AsyncSession, *, telegram_chat_id: int, name: str) -> Group:
    g = Group(telegram_chat_id=telegram_chat_id, name=name, is_active=True)
    session.add(g)
    await session.flush()
    return g


async def deactivate(session: AsyncSession, group: Group) -> None:
    group.is_active = False
    await session.flush()
