"""回群密钥相关查询：active 列表 / 失败尝试计数 / 成功使用计数 / 日志写入。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.enums import RK_ACTIVE
from bccy_bot.db.models.recovery_key import RecoveryKey
from bccy_bot.db.models.recovery_key_attempt import RecoveryKeyAttempt


# 失败结果集（用于 1h/key 的速率限制）
FAILED_RESULTS = (
    "not_found",
    "same_id",
    "blacklisted",
    "inviter_inactive",
    "rate_limited",
)


async def list_active_keys(session: AsyncSession) -> list[RecoveryKey]:
    result = await session.execute(select(RecoveryKey).where(RecoveryKey.status == RK_ACTIVE))
    return list(result.scalars().all())


async def get_active_key_for_application(
    session: AsyncSession, application_id: int
) -> RecoveryKey | None:
    result = await session.execute(
        select(RecoveryKey)
        .where(
            RecoveryKey.application_id == application_id,
            RecoveryKey.status == RK_ACTIVE,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_used_for_app_and_claimer(
    session: AsyncSession, *, application_id: int, claimer_telegram_id: int
) -> RecoveryKey | None:
    """查找一条「status=used，application_id 匹配，且 used_by 等于 claimer」的密钥。

    chat_member 监听新账号入群时用来识别这是回群密钥救济场景：
    若返回非 None，本次入群应记为「用户回群」而非异常告警。
    """
    from bccy_bot.db.models.enums import RK_USED

    result = await session.execute(
        select(RecoveryKey)
        .where(
            RecoveryKey.application_id == application_id,
            RecoveryKey.used_by_telegram_id == claimer_telegram_id,
            RecoveryKey.status == RK_USED,
        )
        .order_by(RecoveryKey.used_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_active_key_for_owner(
    session: AsyncSession, owner_telegram_id: int
) -> RecoveryKey | None:
    result = await session.execute(
        select(RecoveryKey)
        .where(
            RecoveryKey.owner_telegram_id == owner_telegram_id,
            RecoveryKey.status == RK_ACTIVE,
        )
        .order_by(RecoveryKey.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def record_attempt(
    session: AsyncSession,
    *,
    key_hash: str | None,
    attempted_by_telegram_id: int,
    result: str,
) -> RecoveryKeyAttempt:
    row = RecoveryKeyAttempt(
        key_hash_attempted=key_hash,
        attempted_by_telegram_id=attempted_by_telegram_id,
        result=result,
    )
    session.add(row)
    await session.flush()
    return row


async def count_failed_for_key_within(
    session: AsyncSession, *, key_hash: str, hours: float
) -> int:
    """单密钥 N 小时内累计失败次数（用于 1h/5 锁）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await session.execute(
        select(func.count(RecoveryKeyAttempt.id)).where(
            RecoveryKeyAttempt.key_hash_attempted == key_hash,
            RecoveryKeyAttempt.result.in_(FAILED_RESULTS),
            RecoveryKeyAttempt.attempted_at >= cutoff,
        )
    )
    return int(result.scalar_one())


async def count_success_for_claimer_within(
    session: AsyncSession, *, claimer_telegram_id: int, hours: float
) -> int:
    """单新 Telegram ID 在 N 小时内成功使用密钥的次数（用于 24h/3 锁）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await session.execute(
        select(func.count(RecoveryKeyAttempt.id)).where(
            RecoveryKeyAttempt.attempted_by_telegram_id == claimer_telegram_id,
            RecoveryKeyAttempt.result == "success",
            RecoveryKeyAttempt.attempted_at >= cutoff,
        )
    )
    return int(result.scalar_one())
