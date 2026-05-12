from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.enums import REI_TIER_DEFAULT_CENTS, REI_TIER_VALUES_CENTS
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
    reimbursement_tier_cents: int = REI_TIER_DEFAULT_CENTS,
) -> Inviter:
    if reimbursement_tier_cents not in REI_TIER_VALUES_CENTS:
        raise ValueError(
            f"reimbursement_tier_cents must be one of {REI_TIER_VALUES_CENTS}, "
            f"got {reimbursement_tier_cents}"
        )
    inv = Inviter(
        telegram_user_id=telegram_user_id,
        display_name=display_name,
        group_label=group_label,
        target_group_id=target_group_id,
        required_materials=list(required_materials),
        review_mode=review_mode,
        reimbursement_tier_cents=reimbursement_tier_cents,
        is_active=True,
    )
    session.add(inv)
    await session.flush()
    return inv


async def toggle_active(session: AsyncSession, inviter: Inviter) -> None:
    inviter.is_active = not inviter.is_active
    await session.flush()


async def update_tier(
    session: AsyncSession, inviter: Inviter, tier_cents: int
) -> None:
    """设置该邀请人的报销档位（仅允许三档其一）。"""
    if tier_cents not in REI_TIER_VALUES_CENTS:
        raise ValueError(
            f"tier_cents must be one of {REI_TIER_VALUES_CENTS}, got {tier_cents}"
        )
    inviter.reimbursement_tier_cents = tier_cents
    await session.flush()


async def delete(session: AsyncSession, inviter: Inviter) -> None:
    await session.delete(inviter)
    await session.flush()
