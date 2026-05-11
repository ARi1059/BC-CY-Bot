"""报销请求 + 材料的 CRUD 与典型查询。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.enums import (
    REI_STATUS_APPROVED,
    REI_STATUS_PAID,
    REI_STATUS_PENDING,
    REI_STATUS_WIZARD,
)
from bccy_bot.db.models.reimbursement_material import ReimbursementMaterial
from bccy_bot.db.models.reimbursement_request import ReimbursementRequest


# ---------- 申请记录 ----------


async def get_active_for_user(
    session: AsyncSession, applicant_telegram_id: int
) -> ReimbursementRequest | None:
    """返回该用户当前"进行中"的报销（wizard / pending），同时只允许一个。"""
    result = await session.execute(
        select(ReimbursementRequest)
        .where(
            ReimbursementRequest.applicant_telegram_id == applicant_telegram_id,
            ReimbursementRequest.status.in_((REI_STATUS_WIZARD, REI_STATUS_PENDING)),
        )
        .order_by(ReimbursementRequest.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_last_completed_for_user(
    session: AsyncSession, applicant_telegram_id: int
) -> ReimbursementRequest | None:
    """最近一次审核通过（approved / paid）的报销，用于冷却时间计算。"""
    result = await session.execute(
        select(ReimbursementRequest)
        .where(
            ReimbursementRequest.applicant_telegram_id == applicant_telegram_id,
            ReimbursementRequest.status.in_((REI_STATUS_APPROVED, REI_STATUS_PAID)),
            ReimbursementRequest.reviewed_at.is_not(None),
        )
        .order_by(ReimbursementRequest.reviewed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_wizard(
    session: AsyncSession,
    *,
    applicant_telegram_id: int,
    applicant_username: str | None,
    applicant_display_name: str | None,
    application_id: int,
    amount_cents: int,
) -> ReimbursementRequest:
    r = ReimbursementRequest(
        applicant_telegram_id=applicant_telegram_id,
        applicant_username=applicant_username,
        applicant_display_name=applicant_display_name,
        application_id=application_id,
        status=REI_STATUS_WIZARD,
        wizard_step=1,
        amount_cents=amount_cents,
    )
    session.add(r)
    await session.flush()
    return r


async def advance_step(
    session: AsyncSession, r: ReimbursementRequest, new_step: int
) -> None:
    r.wizard_step = new_step
    await session.flush()


async def submit(session: AsyncSession, r: ReimbursementRequest) -> None:
    from bccy_bot.db.models.enums import REI_STATUS_PENDING

    r.status = REI_STATUS_PENDING
    r.submitted_at = datetime.now(timezone.utc)
    await session.flush()


async def cancel(session: AsyncSession, r: ReimbursementRequest) -> None:
    from bccy_bot.db.models.enums import REI_STATUS_CANCELLED

    r.status = REI_STATUS_CANCELLED
    await session.flush()


# ---------- 材料 ----------


async def list_materials(
    session: AsyncSession, reimbursement_id: int
) -> list[ReimbursementMaterial]:
    result = await session.execute(
        select(ReimbursementMaterial)
        .where(ReimbursementMaterial.reimbursement_id == reimbursement_id)
        .order_by(ReimbursementMaterial.id)
    )
    return list(result.scalars().all())


async def add_material(
    session: AsyncSession,
    *,
    reimbursement_id: int,
    material_type: str,
    content_type: str,
    telegram_file_id: str | None,
    text_content: str | None,
    original_message_id: int,
) -> ReimbursementMaterial:
    m = ReimbursementMaterial(
        reimbursement_id=reimbursement_id,
        material_type=material_type,
        content_type=content_type,
        telegram_file_id=telegram_file_id,
        text_content=text_content,
        original_message_id=original_message_id,
    )
    session.add(m)
    await session.flush()
    return m


async def clear_materials(session: AsyncSession, reimbursement_id: int) -> None:
    ms = await list_materials(session, reimbursement_id)
    for m in ms:
        await session.delete(m)
    await session.flush()


# ---------- 列表查询（管理面板用） ----------


async def list_pending(session: AsyncSession) -> list[ReimbursementRequest]:
    result = await session.execute(
        select(ReimbursementRequest)
        .where(ReimbursementRequest.status == REI_STATUS_PENDING)
        .order_by(ReimbursementRequest.submitted_at.asc().nullslast())
    )
    return list(result.scalars().all())


async def list_approved_unpaid(session: AsyncSession) -> list[ReimbursementRequest]:
    result = await session.execute(
        select(ReimbursementRequest)
        .where(ReimbursementRequest.status == REI_STATUS_APPROVED)
        .order_by(ReimbursementRequest.reviewed_at.asc().nullslast())
    )
    return list(result.scalars().all())


async def list_recent(session: AsyncSession, limit: int = 30) -> list[ReimbursementRequest]:
    result = await session.execute(
        select(ReimbursementRequest).order_by(ReimbursementRequest.id.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def count_in_range_for_user(
    session: AsyncSession,
    *,
    applicant_telegram_id: int,
    start: datetime,
    end: datetime,
) -> int:
    """统计某用户在 [start, end) 内的成功（approved + paid）报销次数，给周报/月报用。"""
    from sqlalchemy import func

    result = await session.execute(
        select(func.count(ReimbursementRequest.id)).where(
            ReimbursementRequest.applicant_telegram_id == applicant_telegram_id,
            ReimbursementRequest.status.in_((REI_STATUS_APPROVED, REI_STATUS_PAID)),
            ReimbursementRequest.reviewed_at >= start,
            ReimbursementRequest.reviewed_at < end,
        )
    )
    return int(result.scalar_one())
