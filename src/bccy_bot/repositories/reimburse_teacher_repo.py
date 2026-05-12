"""报销老师 CRUD（[v1.0.0-beta.3]）。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.enums import REI_TIER_DEFAULT_CENTS, REI_TIER_VALUES_CENTS
from bccy_bot.db.models.reimburse_teacher import ReimburseTeacher


async def list_all(session: AsyncSession) -> list[ReimburseTeacher]:
    result = await session.execute(
        select(ReimburseTeacher).order_by(ReimburseTeacher.id)
    )
    return list(result.scalars().all())


async def list_active(session: AsyncSession) -> list[ReimburseTeacher]:
    result = await session.execute(
        select(ReimburseTeacher)
        .where(ReimburseTeacher.is_active.is_(True))
        .order_by(ReimburseTeacher.id)
    )
    return list(result.scalars().all())


async def get_by_id(session: AsyncSession, teacher_id: int) -> ReimburseTeacher | None:
    return await session.get(ReimburseTeacher, teacher_id)


async def find_by_username(
    session: AsyncSession, telegram_username: str
) -> ReimburseTeacher | None:
    result = await session.execute(
        select(ReimburseTeacher)
        .where(ReimburseTeacher.telegram_username == telegram_username)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    telegram_username: str,
    display_name: str,
    group_label: str,
    reimbursement_tier_cents: int = REI_TIER_DEFAULT_CENTS,
) -> ReimburseTeacher:
    if reimbursement_tier_cents not in REI_TIER_VALUES_CENTS:
        raise ValueError(
            f"reimbursement_tier_cents must be one of {REI_TIER_VALUES_CENTS}, "
            f"got {reimbursement_tier_cents}"
        )
    t = ReimburseTeacher(
        telegram_username=telegram_username,
        display_name=display_name,
        group_label=group_label,
        reimbursement_tier_cents=reimbursement_tier_cents,
        is_active=True,
    )
    session.add(t)
    await session.flush()
    return t


async def update_tier(
    session: AsyncSession, teacher: ReimburseTeacher, tier_cents: int
) -> None:
    """设置该老师的报销档位（仅允许三档其一）。"""
    if tier_cents not in REI_TIER_VALUES_CENTS:
        raise ValueError(
            f"tier_cents must be one of {REI_TIER_VALUES_CENTS}, got {tier_cents}"
        )
    teacher.reimbursement_tier_cents = tier_cents
    await session.flush()


async def update_group_label(
    session: AsyncSession, teacher: ReimburseTeacher, group_label: str
) -> None:
    teacher.group_label = group_label
    await session.flush()


async def toggle_active(session: AsyncSession, teacher: ReimburseTeacher) -> None:
    teacher.is_active = not teacher.is_active
    await session.flush()


async def delete(session: AsyncSession, teacher: ReimburseTeacher) -> None:
    await session.delete(teacher)
    await session.flush()
