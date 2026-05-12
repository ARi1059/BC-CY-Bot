"""
统计查询服务：邀请人个人面板 + 管理员全局统计 共用。

只暴露纯数据 dataclass，handler 负责文本渲染。
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    APP_STATUS_CANCELLED,
    APP_STATUS_PENDING,
    APP_STATUS_REJECTED,
)
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.db.models.inviter import Inviter


@dataclass
class InviterStats:
    inviter_id: int
    inviter_display: str
    pending: int
    approved: int
    rejected: int
    cancelled: int
    total: int
    links_issued: int
    links_used: int
    link_usage_rate: float | None  # used / issued，0~1；issued=0 时 None

    @property
    def approval_rate(self) -> float | None:
        decided = self.approved + self.rejected
        return (self.approved / decided) if decided else None


@dataclass
class GlobalStats:
    by_status: dict[str, int]
    total: int
    total_links: int
    used_links: int
    anomaly_links: int
    keys_active: int
    keys_used: int
    keys_revoked: int
    keys_reset: int
    per_inviter: list[InviterStats]

    @property
    def approval_rate(self) -> float | None:
        approved = self.by_status.get(APP_STATUS_APPROVED, 0)
        rejected = self.by_status.get(APP_STATUS_REJECTED, 0)
        decided = approved + rejected
        return (approved / decided) if decided else None


# ---------- 邀请人个人统计 ----------


async def compute_inviter_stats(session: AsyncSession, inviter: Inviter) -> InviterStats:
    rows = (
        await session.execute(
            select(Application.status, func.count(Application.id))
            .where(Application.inviter_id == inviter.id)
            .group_by(Application.status)
        )
    ).all()
    counts = {r[0]: r[1] for r in rows}

    pending = counts.get(APP_STATUS_PENDING, 0)
    approved = counts.get(APP_STATUS_APPROVED, 0)
    rejected = counts.get(APP_STATUS_REJECTED, 0)
    cancelled = counts.get(APP_STATUS_CANCELLED, 0)
    total = sum(counts.values())

    # 我名下签发的链接 = 申请关联到我的链接
    link_total = (
        await session.execute(
            select(func.count(InviteLink.id))
            .join(Application, InviteLink.application_id == Application.id)
            .where(Application.inviter_id == inviter.id)
        )
    ).scalar_one()
    link_used = (
        await session.execute(
            select(func.count(InviteLink.id))
            .join(Application, InviteLink.application_id == Application.id)
            .where(Application.inviter_id == inviter.id, InviteLink.is_used.is_(True))
        )
    ).scalar_one()
    usage_rate = (link_used / link_total) if link_total else None

    return InviterStats(
        inviter_id=inviter.id,
        inviter_display=inviter.display_name,
        pending=pending,
        approved=approved,
        rejected=rejected,
        cancelled=cancelled,
        total=total,
        links_issued=link_total,
        links_used=link_used,
        link_usage_rate=usage_rate,
    )


# ---------- 邀请人待审列表 ----------


async def list_pending_for_inviter(session: AsyncSession, inviter_id: int) -> list[Application]:
    """返回归属该邀请人的 pending 申请，按提交时间升序（最先来的先看）。"""
    result = await session.execute(
        select(Application)
        .where(Application.inviter_id == inviter_id, Application.status == APP_STATUS_PENDING)
        .order_by(Application.submitted_at.asc().nullslast(), Application.id.asc())
    )
    return list(result.scalars().all())


# ---------- 管理员全局统计 ----------


async def compute_global_stats(session: AsyncSession) -> GlobalStats:
    from bccy_bot.db.models.enums import RK_ACTIVE, RK_RESET, RK_REVOKED, RK_USED
    from bccy_bot.db.models.recovery_key import RecoveryKey
    from bccy_bot.repositories import inviter_repo

    status_rows = (
        await session.execute(
            select(Application.status, func.count(Application.id)).group_by(Application.status)
        )
    ).all()
    by_status = {r[0]: r[1] for r in status_rows}

    total_links = (await session.execute(select(func.count(InviteLink.id)))).scalar_one()
    used_links = (
        await session.execute(select(func.count(InviteLink.id)).where(InviteLink.is_used.is_(True)))
    ).scalar_one()
    anomaly_links = (
        await session.execute(
            select(func.count(InviteLink.id)).where(InviteLink.is_anomaly.is_(True))
        )
    ).scalar_one()

    key_rows = (
        await session.execute(
            select(RecoveryKey.status, func.count(RecoveryKey.id)).group_by(RecoveryKey.status)
        )
    ).all()
    keys = {r[0]: r[1] for r in key_rows}

    inviters = await inviter_repo.list_all(session)
    per_inviter: list[InviterStats] = []
    for inv in inviters:
        per_inviter.append(await compute_inviter_stats(session, inv))

    return GlobalStats(
        by_status=by_status,
        total=sum(by_status.values()),
        total_links=int(total_links),
        used_links=int(used_links),
        anomaly_links=int(anomaly_links),
        keys_active=keys.get(RK_ACTIVE, 0),
        keys_used=keys.get(RK_USED, 0),
        keys_revoked=keys.get(RK_REVOKED, 0),
        keys_reset=keys.get(RK_RESET, 0),
        per_inviter=per_inviter,
    )
