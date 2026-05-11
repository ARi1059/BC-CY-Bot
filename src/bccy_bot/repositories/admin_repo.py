from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.admin import Admin
from bccy_bot.db.models.audit_log import AuditLog
from bccy_bot.db.models.enums import ROLE_SUB, ROLE_SUPER


async def list_all(session: AsyncSession) -> list[Admin]:
    """所有管理员（super + sub），按 id 升序。代审型审核广播用。"""
    result = await session.execute(select(Admin).order_by(Admin.id))
    return list(result.scalars().all())


async def is_admin(session: AsyncSession, telegram_user_id: int) -> bool:
    result = await session.execute(
        select(Admin.id).where(Admin.telegram_user_id == telegram_user_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def is_super_admin(session: AsyncSession, telegram_user_id: int) -> bool:
    result = await session.execute(
        select(Admin.id)
        .where(Admin.telegram_user_id == telegram_user_id, Admin.role == ROLE_SUPER)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def find_by_telegram_user_id(session: AsyncSession, telegram_user_id: int) -> Admin | None:
    result = await session.execute(
        select(Admin).where(Admin.telegram_user_id == telegram_user_id).limit(1)
    )
    return result.scalar_one_or_none()


async def get_super_admin(session: AsyncSession) -> Admin | None:
    result = await session.execute(select(Admin).where(Admin.role == ROLE_SUPER).limit(1))
    return result.scalar_one_or_none()


async def add_sub_admin(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    display_name: str | None,
    added_by: int | None,
) -> Admin:
    a = Admin(
        telegram_user_id=telegram_user_id,
        display_name=display_name,
        role=ROLE_SUB,
        added_by=added_by,
    )
    session.add(a)
    await session.flush()
    session.add(
        AuditLog(
            actor_telegram_id=None if added_by is None else None,  # 由调用方填
            actor_role="super_admin",
            action="add_sub_admin",
            details={"telegram_user_id": telegram_user_id, "admin_id": a.id},
        )
    )
    return a


async def remove_sub_admin(session: AsyncSession, admin: Admin, *, by_super_telegram_id: int) -> None:
    if admin.role == ROLE_SUPER:
        raise ValueError("cannot remove super admin via this API")
    session.add(
        AuditLog(
            actor_telegram_id=by_super_telegram_id,
            actor_role="super_admin",
            action="remove_sub_admin",
            details={"telegram_user_id": admin.telegram_user_id, "admin_id": admin.id},
        )
    )
    await session.delete(admin)
    await session.flush()


async def transfer_super_admin(
    session: AsyncSession,
    *,
    new_super: Admin,
    current_super: Admin,
    by_telegram_id: int,
) -> None:
    """超级管理员转让：current_super 降级为 sub，new_super 提升为 super。"""
    if current_super.id == new_super.id:
        raise ValueError("source equals target")
    if new_super.role == ROLE_SUPER:
        raise ValueError("target already super")
    # 先降级当前 super，避免触犯 uq_one_super_admin 部分唯一索引
    current_super.role = ROLE_SUB
    await session.flush()
    new_super.role = ROLE_SUPER
    await session.flush()
    session.add(
        AuditLog(
            actor_telegram_id=by_telegram_id,
            actor_role="super_admin",
            action="transfer_super_admin",
            details={
                "from_telegram_id": current_super.telegram_user_id,
                "to_telegram_id": new_super.telegram_user_id,
            },
        )
    )


async def ensure_initial_super_admin(session: AsyncSession, env_super_id: int) -> dict:
    """
    幂等地维护"初始超级管理员"：

    - 全表无超级管理员 → 用 env_super_id 创建
    - 已存在的超级管理员 telegram_user_id == env_super_id → 无操作
    - 不一致 → env 覆盖：旧的降为副管理员（保留），env_super_id 升为超级管理员
      （若 env_super_id 已是副管理员则就地升级，否则新建）

    所有变更写入 audit_logs，actor_role='env_override'。

    返回操作摘要 dict，供启动日志输出。
    """
    current = (
        await session.execute(select(Admin).where(Admin.role == ROLE_SUPER))
    ).scalar_one_or_none()

    if current is None:
        new_admin = Admin(
            telegram_user_id=env_super_id,
            display_name=None,
            role=ROLE_SUPER,
            added_by=None,
        )
        session.add(new_admin)
        await session.flush()
        session.add(
            AuditLog(
                actor_telegram_id=None,
                actor_role="env_override",
                action="create_initial_super_admin",
                details={"telegram_user_id": env_super_id},
            )
        )
        return {"action": "created", "telegram_user_id": env_super_id}

    if current.telegram_user_id == env_super_id:
        return {"action": "noop", "telegram_user_id": env_super_id}

    # 不一致 → 覆盖
    old_id = current.telegram_user_id

    target = (
        await session.execute(select(Admin).where(Admin.telegram_user_id == env_super_id))
    ).scalar_one_or_none()

    # 先降级旧的，避免违反"至多 1 个 super"的部分唯一索引
    current.role = ROLE_SUB
    await session.flush()

    if target is None:
        session.add(
            Admin(
                telegram_user_id=env_super_id,
                display_name=None,
                role=ROLE_SUPER,
                added_by=None,
            )
        )
    else:
        target.role = ROLE_SUPER

    await session.flush()

    session.add(
        AuditLog(
            actor_telegram_id=None,
            actor_role="env_override",
            action="override_super_admin",
            details={"old_super_telegram_id": old_id, "new_super_telegram_id": env_super_id},
        )
    )
    return {"action": "overridden", "old": old_id, "new": env_super_id}
