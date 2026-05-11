from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.admin import Admin
from bccy_bot.db.models.audit_log import AuditLog
from bccy_bot.db.models.enums import ROLE_SUB, ROLE_SUPER


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
