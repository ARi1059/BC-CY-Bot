"""单用户冷却覆盖 CRUD。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.reimbursement_user_override import ReimbursementUserOverride


async def list_all(session: AsyncSession) -> list[ReimbursementUserOverride]:
    result = await session.execute(
        select(ReimbursementUserOverride).order_by(ReimbursementUserOverride.id)
    )
    return list(result.scalars().all())


async def find_for_user(
    session: AsyncSession, telegram_user_id: int
) -> ReimbursementUserOverride | None:
    result = await session.execute(
        select(ReimbursementUserOverride)
        .where(ReimbursementUserOverride.telegram_user_id == telegram_user_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def upsert(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    cooldown_days: int,
    notes: str | None,
    added_by: int | None,
) -> ReimbursementUserOverride:
    existing = await find_for_user(session, telegram_user_id)
    if existing is not None:
        existing.cooldown_days = cooldown_days
        existing.notes = notes
        await session.flush()
        return existing
    row = ReimbursementUserOverride(
        telegram_user_id=telegram_user_id,
        cooldown_days=cooldown_days,
        notes=notes,
        added_by=added_by,
    )
    session.add(row)
    await session.flush()
    return row


async def remove(session: AsyncSession, override: ReimbursementUserOverride) -> None:
    await session.delete(override)
    await session.flush()
