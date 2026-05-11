from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.inviter import Inviter


async def list_active(session: AsyncSession) -> list[Inviter]:
    """列出所有 is_active=True 的邀请人，按 id 升序（决定 wizard 列表展示顺序）。"""
    result = await session.execute(
        select(Inviter).where(Inviter.is_active.is_(True)).order_by(Inviter.id)
    )
    return list(result.scalars().all())


async def list_all(session: AsyncSession) -> list[Inviter]:
    result = await session.execute(select(Inviter).order_by(Inviter.id))
    return list(result.scalars().all())


async def get_by_id(session: AsyncSession, inviter_id: int) -> Inviter | None:
    return await session.get(Inviter, inviter_id)


async def find_by_telegram_user_id(
    session: AsyncSession, telegram_user_id: int
) -> Inviter | None:
    """根据 Telegram 用户 ID 查找邀请人（用于 /panel 权限校验）。"""
    result = await session.execute(
        select(Inviter).where(Inviter.telegram_user_id == telegram_user_id).limit(1)
    )
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    telegram_user_id: int | None,
    display_name: str,
    group_label: str,
    target_group_id: int,
    required_materials: list[str],
    review_mode: str,
) -> Inviter:
    inv = Inviter(
        telegram_user_id=telegram_user_id,
        display_name=display_name,
        group_label=group_label,
        target_group_id=target_group_id,
        required_materials=list(required_materials),
        review_mode=review_mode,
        is_active=True,
    )
    session.add(inv)
    await session.flush()
    return inv


async def toggle_active(session: AsyncSession, inviter: Inviter) -> None:
    inviter.is_active = not inviter.is_active
    await session.flush()


async def delete(session: AsyncSession, inviter: Inviter) -> None:
    await session.delete(inviter)
    await session.flush()
