from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.inviter import Inviter


async def list_active(session: AsyncSession) -> list[Inviter]:
    """列出所有 is_active=True 的邀请人，按 id 升序（决定 wizard 列表展示顺序）。"""
    result = await session.execute(
        select(Inviter).where(Inviter.is_active.is_(True)).order_by(Inviter.id)
    )
    return list(result.scalars().all())


async def get_by_id(session: AsyncSession, inviter_id: int) -> Inviter | None:
    return await session.get(Inviter, inviter_id)
