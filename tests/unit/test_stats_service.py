"""stats_service：邀请人个人统计 + 全局统计。"""

from datetime import datetime, timezone

import pytest

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    APP_STATUS_CANCELLED,
    APP_STATUS_PENDING,
    APP_STATUS_REJECTED,
    MAT_REPORT,
    REVIEW_MODE_SELF,
    RK_ACTIVE,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.db.models.recovery_key import RecoveryKey
from bccy_bot.services import stats_service


# ---------- 数据准备 ----------


async def _seed_inviter(session, *, label: str, telegram_user_id: int) -> Inviter:
    grp = Group(telegram_chat_id=-100 * abs(hash(label)) % 100000 - 100, name=f"g-{label}")
    session.add(grp)
    await session.flush()
    inv = Inviter(
        telegram_user_id=telegram_user_id,
        display_name=label,
            target_group_id=grp.id,
        required_materials=[MAT_REPORT],
        review_mode=REVIEW_MODE_SELF,
        is_active=True,
    )
    session.add(inv)
    await session.flush()
    return inv


async def _add_apps(session, inviter: Inviter, status_counts: dict[str, int]) -> list[Application]:
    apps: list[Application] = []
    counter = 0
    for status, n in status_counts.items():
        for _ in range(n):
            counter += 1
            app = Application(
                applicant_telegram_id=10000 + counter,
                applicant_username=f"u{counter}",
                inviter_id=inviter.id,
                status=status,
                wizard_step=0,
                submitted_at=datetime(2026, 5, 12, 14, counter % 60, tzinfo=timezone.utc),
            )
            session.add(app)
            apps.append(app)
    await session.flush()
    return apps


async def _add_link(session, application: Application, *, is_used: bool, group_id: int) -> InviteLink:
    link = InviteLink(
        application_id=application.id,
        invite_link=f"https://t.me/+x{application.id}",
        invite_link_name=f"App-{application.id}",
        group_id=group_id,
        expire_date=datetime.now(timezone.utc),
        is_used=is_used,
    )
    session.add(link)
    await session.flush()
    return link


# ---------- 邀请人个人统计 ----------


@pytest.mark.asyncio
async def test_inviter_stats_zero_baseline(session):
    inv = await _seed_inviter(session, label="Zhang", telegram_user_id=1)
    s = await stats_service.compute_inviter_stats(session, inv)
    assert s.total == 0
    assert s.pending == 0
    assert s.approval_rate is None
    assert s.link_usage_rate is None


@pytest.mark.asyncio
async def test_inviter_stats_aggregates_status_correctly(session):
    inv = await _seed_inviter(session, label="Li", telegram_user_id=2)
    await _add_apps(session, inv, {
        APP_STATUS_PENDING: 2,
        APP_STATUS_APPROVED: 8,
        APP_STATUS_REJECTED: 1,
        APP_STATUS_CANCELLED: 1,
    })
    s = await stats_service.compute_inviter_stats(session, inv)
    assert s.total == 12
    assert s.pending == 2
    assert s.approved == 8
    assert s.rejected == 1
    assert s.cancelled == 1
    # approval rate = 8 / (8+1) = 88.9%
    assert s.approval_rate is not None
    assert abs(s.approval_rate - 8 / 9) < 1e-6


@pytest.mark.asyncio
async def test_inviter_stats_link_usage(session):
    inv = await _seed_inviter(session, label="Wang", telegram_user_id=3)
    apps = await _add_apps(session, inv, {APP_STATUS_APPROVED: 4})
    # 2 个使用 / 2 个未使用
    await _add_link(session, apps[0], is_used=True, group_id=inv.target_group_id)
    await _add_link(session, apps[1], is_used=True, group_id=inv.target_group_id)
    await _add_link(session, apps[2], is_used=False, group_id=inv.target_group_id)
    await _add_link(session, apps[3], is_used=False, group_id=inv.target_group_id)

    s = await stats_service.compute_inviter_stats(session, inv)
    assert s.links_issued == 4
    assert s.links_used == 2
    assert s.link_usage_rate == 0.5


# ---------- 待审列表 ----------


@pytest.mark.asyncio
async def test_pending_list_only_returns_pending_for_inviter(session):
    inv_a = await _seed_inviter(session, label="A", telegram_user_id=10)
    inv_b = await _seed_inviter(session, label="B", telegram_user_id=20)
    await _add_apps(session, inv_a, {APP_STATUS_PENDING: 3, APP_STATUS_APPROVED: 1})
    await _add_apps(session, inv_b, {APP_STATUS_PENDING: 1})

    a_pending = await stats_service.list_pending_for_inviter(session, inv_a.id)
    assert len(a_pending) == 3
    assert all(a.status == APP_STATUS_PENDING for a in a_pending)
    assert all(a.inviter_id == inv_a.id for a in a_pending)


# ---------- 全局统计 ----------


@pytest.mark.asyncio
async def test_global_stats_aggregates_everything(session):
    inv_a = await _seed_inviter(session, label="A", telegram_user_id=10)
    inv_b = await _seed_inviter(session, label="B", telegram_user_id=20)
    apps_a = await _add_apps(session, inv_a, {APP_STATUS_APPROVED: 5, APP_STATUS_REJECTED: 1})
    await _add_apps(session, inv_b, {APP_STATUS_PENDING: 2})
    await _add_link(session, apps_a[0], is_used=True, group_id=inv_a.target_group_id)
    await _add_link(session, apps_a[1], is_used=False, group_id=inv_a.target_group_id)
    # 一个异常
    link_anom = await _add_link(session, apps_a[2], is_used=True, group_id=inv_a.target_group_id)
    link_anom.is_anomaly = True
    await session.flush()
    # recovery keys
    session.add(
        RecoveryKey(
            application_id=apps_a[0].id,
            owner_telegram_id=10001,
            original_owner_telegram_id=10001,
            key_hash="hash1",
            key_prefix="BCCY-AAAA",
            status=RK_ACTIVE,
        )
    )
    await session.flush()

    s = await stats_service.compute_global_stats(session)
    assert s.total == 8
    assert s.by_status.get(APP_STATUS_APPROVED) == 5
    assert s.by_status.get(APP_STATUS_PENDING) == 2
    assert s.total_links == 3
    assert s.used_links == 2
    assert s.anomaly_links == 1
    assert s.keys_active == 1
    # per_inviter 含两位邀请人，且 inv_a 的总数 = 6
    by_id = {p.inviter_id: p for p in s.per_inviter}
    assert by_id[inv_a.id].total == 6
    assert by_id[inv_b.id].total == 2
    # 通过率 = 5/(5+1)
    assert abs(by_id[inv_a.id].approval_rate - 5 / 6) < 1e-6
