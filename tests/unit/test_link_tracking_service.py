"""链接使用追踪 + 过期扫描的单元测试。"""

from datetime import datetime, timedelta, timezone

import pytest

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import APP_STATUS_APPROVED
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.services import link_tracking_service


_chat_id_counter = -100000


def _next_chat_id() -> int:
    global _chat_id_counter
    _chat_id_counter -= 1
    return _chat_id_counter


async def _seed_link(
    session,
    *,
    applicant_id: int = 42,
    name: str = "App-1",
    is_used: bool = False,
    expires_in_hours: float = 24.0,
) -> tuple[Application, InviteLink, Group]:
    grp = Group(telegram_chat_id=_next_chat_id(), name="g")
    session.add(grp)
    await session.flush()

    app = Application(
        applicant_telegram_id=applicant_id,
        applicant_username="u",
        applicant_display_name="U",
        inviter_id=None,
        status=APP_STATUS_APPROVED,
        wizard_step=0,
    )
    session.add(app)
    await session.flush()

    link = InviteLink(
        application_id=app.id,
        invite_link=f"https://t.me/+fake_{name}",
        invite_link_name=name,
        group_id=grp.id,
        expire_date=datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
        is_used=is_used,
        is_anomaly=False,
    )
    session.add(link)
    await session.flush()
    return app, link, grp


# ---------- on_member_joined ----------


@pytest.mark.asyncio
async def test_normal_join_marks_used_not_anomaly(session):
    app, link, _ = await _seed_link(session)
    result = await link_tracking_service.on_member_joined(
        session, invite_link_name=link.invite_link_name, joined_user_id=app.applicant_telegram_id
    )
    assert result is not None
    assert result.is_used is True
    assert result.used_by_telegram_id == app.applicant_telegram_id
    assert result.used_at is not None
    assert result.is_anomaly is False


@pytest.mark.asyncio
async def test_anomaly_join_marks_is_anomaly(session):
    app, link, _ = await _seed_link(session)
    stranger_id = app.applicant_telegram_id + 9999

    result = await link_tracking_service.on_member_joined(
        session, invite_link_name=link.invite_link_name, joined_user_id=stranger_id
    )
    assert result is not None
    assert result.is_used is True
    assert result.used_by_telegram_id == stranger_id
    assert result.is_anomaly is True


@pytest.mark.asyncio
async def test_unknown_link_name_returns_none(session):
    await _seed_link(session, name="App-7")
    result = await link_tracking_service.on_member_joined(
        session, invite_link_name="App-999", joined_user_id=1
    )
    assert result is None


@pytest.mark.asyncio
async def test_already_used_link_is_safe(session):
    app, link, _ = await _seed_link(session, is_used=True)
    # 已被标记 is_used，find_active_by_name 不会返回，所以无后续动作
    result = await link_tracking_service.on_member_joined(
        session, invite_link_name=link.invite_link_name, joined_user_id=app.applicant_telegram_id
    )
    assert result is None  # 因为 find_active_by_name 过滤掉了已使用的


@pytest.mark.asyncio
async def test_link_for_deleted_application_treated_as_anomaly(session):
    """如果链接关联的申请被异常删除（理论上不应发生），仍能落库，不崩溃。"""
    app, link, _ = await _seed_link(session)
    await session.delete(app)
    await session.flush()

    result = await link_tracking_service.on_member_joined(
        session, invite_link_name=link.invite_link_name, joined_user_id=1
    )
    assert result is not None
    assert result.is_used is True
    # 无法对比 applicant_id → is_anomaly 保持 False（保守处理）
    assert result.is_anomaly is False


# ---------- sweep_expired ----------


@pytest.mark.asyncio
async def test_sweep_marks_expired_unused_links(session):
    # 已过期 1 小时
    _, expired_link, _ = await _seed_link(session, name="App-100", expires_in_hours=-1)
    # 仍有效（未来 1 小时）
    _, fresh_link, _ = await _seed_link(session, applicant_id=43, name="App-101", expires_in_hours=1)
    # 已过期但已使用 —— 不该再被标记
    _, used_link, _ = await _seed_link(
        session, applicant_id=44, name="App-102", is_used=True, expires_in_hours=-1
    )

    marked = await link_tracking_service.sweep_expired(session)

    marked_ids = {m.id for m in marked}
    assert expired_link.id in marked_ids
    assert fresh_link.id not in marked_ids
    assert used_link.id not in marked_ids

    # 已标记的链接 expired_notified_at 写入
    await session.refresh(expired_link)
    assert expired_link.expired_notified_at is not None


@pytest.mark.asyncio
async def test_sweep_is_idempotent(session):
    """同一链接二次 sweep 不会再次推送。"""
    _, link, _ = await _seed_link(session, expires_in_hours=-1)

    first = await link_tracking_service.sweep_expired(session)
    assert len(first) == 1

    second = await link_tracking_service.sweep_expired(session)
    assert second == []  # expired_notified_at 已写，不再被命中
