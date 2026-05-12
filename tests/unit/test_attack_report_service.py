"""attack_report_service：转发 / 无报告 / 无频道 / 失败 四路径。"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.application_material import ApplicationMaterial
from bccy_bot.db.models.attack_report_forward import AttackReportForward
from bccy_bot.db.models.enums import (
    APP_STATUS_PENDING,
    ARF_FAILED,
    ARF_SENT,
    ARF_SKIPPED_NO_CHANNEL,
    ARF_SKIPPED_NO_REPORT,
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REVIEW_MODE_SELF,
    SK_ATTACK_REPORT_CHANNEL_ID,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.repositories import settings_repo
from bccy_bot.services import attack_report_service
from tests.unit.test_audit_service import FakeBot


REPORT_CHANNEL_ID = -1001888888
REPORT_ORIGINAL_MSG_ID = 8001


async def _bind_channel(session) -> None:
    await settings_repo.set_value(session, SK_ATTACK_REPORT_CHANNEL_ID, str(REPORT_CHANNEL_ID))


async def _seed_application(session, *, with_report: bool = True) -> Application:
    grp = Group(telegram_chat_id=-100123, name="g")
    session.add(grp)
    await session.flush()
    inv = Inviter(
        telegram_user_id=111,
        display_name="张老师",
            target_group_id=grp.id,
        required_materials=[MAT_BOOKING, MAT_GESTURE, MAT_REPORT] if with_report else [MAT_BOOKING],
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
    session.add(
        ApplicationMaterial(
            application_id=app.id,
        material_type=MAT_BOOKING,
            content_type=CT_PHOTO,
            telegram_file_id="booking-fid",
            text_content=None,
            original_message_id=100,
        )
    )
    if with_report:
        session.add(
            ApplicationMaterial(
            application_id=app.id,
        material_type=MAT_REPORT,
                content_type=CT_TEXT,
                telegram_file_id=None,
                text_content="今天出击 5 次成功",
                original_message_id=REPORT_ORIGINAL_MSG_ID,
            )
        )
    await session.flush()
    return app


# ---------- 正常转发 ----------


@pytest.mark.asyncio
async def test_forwards_only_report_message(session):
    await _bind_channel(session)
    app = await _seed_application(session)
    bot = FakeBot()

    record = await attack_report_service.forward_report(session, bot, app)

    assert record.status == ARF_SENT
    assert record.channel_id == REPORT_CHANNEL_ID
    assert record.telegram_message_id is not None

    assert len(bot.forwarded) == 1
    fwd = bot.forwarded[0]
    assert fwd.chat_id == REPORT_CHANNEL_ID
    assert fwd.from_chat_id == app.applicant_telegram_id
    assert fwd.source_message_id == REPORT_ORIGINAL_MSG_ID  # ★ 仅转发报告材料的原 msg_id

    # 严格边界：未误发约课记录/上课手势/卡片
    assert bot.sent_texts == []
    assert bot.sent_media == []


# ---------- 跳过路径 ----------


@pytest.mark.asyncio
async def test_skips_when_no_report_material(session):
    await _bind_channel(session)
    app = await _seed_application(session, with_report=False)
    bot = FakeBot()
    record = await attack_report_service.forward_report(session, bot, app)
    assert record.status == ARF_SKIPPED_NO_REPORT
    assert bot.forwarded == []


@pytest.mark.asyncio
async def test_skips_when_channel_unconfigured(session):
    app = await _seed_application(session)
    bot = FakeBot()
    record = await attack_report_service.forward_report(session, bot, app)
    assert record.status == ARF_SKIPPED_NO_CHANNEL
    assert record.channel_id is None
    assert bot.forwarded == []


@pytest.mark.asyncio
async def test_malformed_channel_id_treated_as_unconfigured(session):
    await settings_repo.set_value(session, SK_ATTACK_REPORT_CHANNEL_ID, "not_a_number")
    app = await _seed_application(session)
    bot = FakeBot()
    record = await attack_report_service.forward_report(session, bot, app)
    assert record.status == ARF_SKIPPED_NO_CHANNEL


# ---------- 失败路径 ----------


@pytest.mark.asyncio
async def test_records_failure_when_forward_raises_badrequest(session):
    await _bind_channel(session)
    app = await _seed_application(session)
    bot = FakeBot()
    bot.forward_should_fail = True

    record = await attack_report_service.forward_report(session, bot, app)
    assert record.status == ARF_FAILED
    assert record.error is not None
    assert "simulated forward failure" in record.error
    assert record.telegram_message_id is None


# ---------- 跨记录持久化（多次调用） ----------


@pytest.mark.asyncio
async def test_each_call_writes_one_row(session):
    await _bind_channel(session)
    app = await _seed_application(session)
    bot = FakeBot()

    await attack_report_service.forward_report(session, bot, app)
    await attack_report_service.forward_report(session, bot, app)

    rows = (await session.execute(select(AttackReportForward))).scalars().all()
    assert len(rows) == 2  # 两次尝试都各写一行（便于追溯重试历史）
    assert all(r.status == ARF_SENT for r in rows)


# ---------- channel_id 快照：变更频道后历史记录保留旧 ID ----------


@pytest.mark.asyncio
async def test_channel_id_snapshot_persists(session):
    await _bind_channel(session)
    app = await _seed_application(session)
    bot = FakeBot()
    record = await attack_report_service.forward_report(session, bot, app)
    snapped = record.channel_id
    assert snapped == REPORT_CHANNEL_ID

    # 模拟管理员改了频道配置
    await settings_repo.set_value(session, SK_ATTACK_REPORT_CHANNEL_ID, "-1001777777")
    await session.refresh(record)
    assert record.channel_id == snapped  # 旧记录不变
