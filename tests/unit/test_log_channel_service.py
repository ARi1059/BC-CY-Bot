"""log_channel_service：5 类事件卡片 + 频道未配置/失败容错。"""

from datetime import datetime, timezone

import pytest

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import (
    APP_STATUS_PENDING,
    MAT_REPORT,
    REVIEW_MODE_SELF,
    SK_LOG_CHANNEL_ID,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.repositories import settings_repo
from bccy_bot.services import log_channel_service
from tests.unit.test_audit_service import FakeBot


CHANNEL_ID = -1001999999


async def _bind_channel(session) -> None:
    await settings_repo.set_value(session, SK_LOG_CHANNEL_ID, str(CHANNEL_ID))


async def _seed_pending(session) -> tuple[Application, Inviter]:
    grp = Group(telegram_chat_id=-100123, name="g")
    session.add(grp)
    await session.flush()
    inv = Inviter(
        telegram_user_id=111,
        display_name="张老师",
            target_group_id=grp.id,
        required_materials=[MAT_REPORT],
        review_mode=REVIEW_MODE_SELF,
        is_active=True,
    )
    session.add(inv)
    await session.flush()
    app = Application(
        applicant_telegram_id=42,
        applicant_username="alice",
        inviter_id=inv.id,
        status=APP_STATUS_PENDING,
        wizard_step=0,
        submitted_at=datetime(2026, 5, 12, 14, 23, tzinfo=timezone.utc),
    )
    session.add(app)
    await session.flush()
    return app, inv


# ---------- 频道未配置：静默跳过 ----------


@pytest.mark.asyncio
async def test_new_application_skipped_when_channel_unconfigured(session):
    app, _ = await _seed_pending(session)
    bot = FakeBot()
    await log_channel_service.push_new_application(session, bot, app)
    assert bot.sent_texts == []


# ---------- 5 类事件卡片 ----------


@pytest.mark.asyncio
async def test_new_application_card(session):
    await _bind_channel(session)
    app, _ = await _seed_pending(session)
    bot = FakeBot()
    await log_channel_service.push_new_application(session, bot, app)
    assert len(bot.sent_texts) == 1
    msg = bot.sent_texts[0]
    assert msg.chat_id == CHANNEL_ID
    assert "📥 新申请待审核" in msg.text
    assert f"#A{app.id}" in msg.text
    assert "@alice" in msg.text
    assert "张老师" in msg.text


@pytest.mark.asyncio
async def test_approval_card(session):
    await _bind_channel(session)
    app, _ = await _seed_pending(session)
    bot = FakeBot()
    await log_channel_service.push_approval(
        session, bot, app,
        reviewer_telegram_id=111,
        reviewer_role="inviter",
        reviewer_display="@zhang",
        invite_link_url="https://t.me/+ABCDEFGHIJK",
    )
    msg = bot.sent_texts[0]
    assert "✅ 审核通过" in msg.text
    assert "@zhang" in msg.text
    assert "邀请人" in msg.text
    # 链接脱敏：保留前 4 个字符 + ****
    assert "https://t.me/+ABCD****" in msg.text
    assert "ABCDEFGHIJK" not in msg.text


@pytest.mark.asyncio
async def test_rejection_card_with_reason(session):
    await _bind_channel(session)
    app, _ = await _seed_pending(session)
    bot = FakeBot()
    await log_channel_service.push_rejection(
        session, bot, app,
        reviewer_telegram_id=111,
        reviewer_role="inviter",
        reviewer_display="@zhang",
        reason="材料不齐",
    )
    msg = bot.sent_texts[0]
    assert "❌ 审核拒绝" in msg.text
    assert "材料不齐" in msg.text


@pytest.mark.asyncio
async def test_rejection_card_without_reason(session):
    await _bind_channel(session)
    app, _ = await _seed_pending(session)
    bot = FakeBot()
    await log_channel_service.push_rejection(
        session, bot, app,
        reviewer_telegram_id=111,
        reviewer_role="admin",
        reviewer_display="@admin",
        reason=None,
    )
    msg = bot.sent_texts[0]
    assert "（未填写）" in msg.text


@pytest.mark.asyncio
async def test_link_used_card_consistent(session):
    await _bind_channel(session)
    app, _ = await _seed_pending(session)
    link = InviteLink(
        application_id=app.id,
        invite_link="https://t.me/+xxxxFAKE12345",
        invite_link_name=f"App-{app.id}",
        group_id=1,
        expire_date=datetime.now(timezone.utc),
        is_used=True,
        used_by_telegram_id=42,
        is_anomaly=False,
    )
    session.add(link)
    await session.flush()
    bot = FakeBot()
    await log_channel_service.push_link_used(
        session, bot, app, link,
        joined_user_id=42, joined_username="alice",
    )
    msg = bot.sent_texts[0]
    assert "🚪 链接已使用" in msg.text
    assert "✓ 一致" in msg.text
    assert "@alice" in msg.text


@pytest.mark.asyncio
async def test_anomaly_card_inconsistent(session):
    await _bind_channel(session)
    app, _ = await _seed_pending(session)
    link = InviteLink(
        application_id=app.id,
        invite_link="https://t.me/+yyyy",
        invite_link_name=f"App-{app.id}",
        group_id=1,
        expire_date=datetime.now(timezone.utc),
        is_used=True,
        used_by_telegram_id=999,
        is_anomaly=True,
    )
    session.add(link)
    await session.flush()
    bot = FakeBot()
    await log_channel_service.push_anomaly(
        session, bot, app, link,
        joined_user_id=999, joined_username="stranger",
    )
    msg = bot.sent_texts[0]
    assert "⚠️ 异常告警" in msg.text
    assert "不一致" in msg.text
    assert "@stranger" in msg.text


@pytest.mark.asyncio
async def test_link_expired_card(session):
    await _bind_channel(session)
    app, _ = await _seed_pending(session)
    link = InviteLink(
        application_id=app.id,
        invite_link="https://t.me/+old",
        invite_link_name=f"App-{app.id}",
        group_id=1,
        expire_date=datetime(2026, 5, 11, 0, 0, tzinfo=timezone.utc),
        is_used=False,
        is_anomaly=False,
    )
    session.add(link)
    await session.flush()
    bot = FakeBot()
    await log_channel_service.push_link_expired(session, bot, link)
    msg = bot.sent_texts[0]
    assert "链接过期未用" in msg.text
    assert "#链接过期" in msg.text
    assert f"App-{app.id}" in msg.text


# ---------- 容错：channel id 非法 ----------


@pytest.mark.asyncio
async def test_malformed_channel_id_treated_as_unconfigured(session):
    await settings_repo.set_value(session, SK_LOG_CHANNEL_ID, "not_a_number")
    app, _ = await _seed_pending(session)
    bot = FakeBot()
    await log_channel_service.push_new_application(session, bot, app)
    assert bot.sent_texts == []
