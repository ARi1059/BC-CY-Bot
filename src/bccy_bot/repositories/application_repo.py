from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.application_material import ApplicationMaterial
from bccy_bot.db.models.enums import (
    APP_STATUS_CANCELLED,
    APP_STATUS_PENDING,
    APP_STATUS_WIZARD,
)


async def get_active_for_user(session: AsyncSession, applicant_telegram_id: int) -> Application | None:
    """
    返回该 Telegram 用户当前"还在进行中"的申请：
    - status='wizard' (流程中)
    - status='pending' (已提交待审核)

    用于：
    - /start 时判断是否已有进行中申请（同一申请人不允许并发申请）
    - wizard 内回到 /start 时恢复状态
    """
    result = await session.execute(
        select(Application)
        .where(
            Application.applicant_telegram_id == applicant_telegram_id,
            Application.status.in_((APP_STATUS_WIZARD, APP_STATUS_PENDING)),
        )
        .order_by(Application.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_wizard(
    session: AsyncSession,
    applicant_telegram_id: int,
    applicant_username: str | None,
    applicant_display_name: str | None,
) -> Application:
    app = Application(
        applicant_telegram_id=applicant_telegram_id,
        applicant_username=applicant_username,
        applicant_display_name=applicant_display_name,
        inviter_id=None,
        status=APP_STATUS_WIZARD,
        wizard_step=0,
    )
    session.add(app)
    await session.flush()
    return app


async def set_inviter(session: AsyncSession, application: Application, inviter_id: int) -> None:
    application.inviter_id = inviter_id
    application.wizard_step = 1  # 进入第一项材料收集
    await session.flush()


async def advance_wizard_step(session: AsyncSession, application: Application, new_step: int) -> None:
    application.wizard_step = new_step
    await session.flush()


async def cancel(session: AsyncSession, application: Application) -> None:
    application.status = APP_STATUS_CANCELLED
    application.wizard_step = 0
    await session.flush()


async def submit(session: AsyncSession, application: Application) -> None:
    application.status = APP_STATUS_PENDING
    application.submitted_at = datetime.now(timezone.utc)
    await session.flush()


async def list_materials(session: AsyncSession, application_id: int) -> list[ApplicationMaterial]:
    result = await session.execute(
        select(ApplicationMaterial)
        .where(ApplicationMaterial.application_id == application_id)
        .order_by(ApplicationMaterial.id)
    )
    return list(result.scalars().all())


async def clear_materials(session: AsyncSession, application_id: int) -> None:
    """重新提交时清空已有材料，wizard_step 回到 1。"""
    materials = await list_materials(session, application_id)
    for m in materials:
        await session.delete(m)
    await session.flush()
