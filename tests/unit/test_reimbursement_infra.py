"""M11 报销基础设施：仓库 CRUD + 设置读写 + 资格列表增删 + 用户冷却覆盖。"""

import pytest

from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REI_STATUS_APPROVED,
    REI_STATUS_PAID,
    REI_STATUS_PENDING,
    REI_STATUS_WIZARD,
    REVIEW_MODE_SELF,
)
from bccy_bot.repositories import (
    eligibility_chat_repo,
    reimbursement_override_repo,
    reimbursement_repo,
    reimbursement_settings,
)


# ---------- 数据准备 ----------


async def _seed_approved_application(session, applicant_id: int = 100):
    """种入一份 approved 的入群申请，供报销关联。"""
    from datetime import datetime, timezone

    from bccy_bot.db.models.application import Application
    from bccy_bot.db.models.group import Group
    from bccy_bot.db.models.inviter import Inviter

    g = Group(telegram_chat_id=-100200 - applicant_id, name="g")
    session.add(g)
    await session.flush()
    inv = Inviter(
        telegram_user_id=200,
        display_name="x",
        group_label="A",
        target_group_id=g.id,
        required_materials=[MAT_REPORT],
        review_mode=REVIEW_MODE_SELF,
        is_active=True,
    )
    session.add(inv)
    await session.flush()
    app = Application(
        applicant_telegram_id=applicant_id,
        applicant_username="u",
        inviter_id=inv.id,
        status=APP_STATUS_APPROVED,
        wizard_step=0,
        reviewed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    session.add(app)
    await session.flush()
    return app


# ---------- reimbursement_settings ----------


@pytest.mark.asyncio
async def test_settings_defaults_when_empty(session):
    assert (await reimbursement_settings.is_enabled(session)) is False
    assert (await reimbursement_settings.get_fixed_amount_cents(session)) == 0
    assert (await reimbursement_settings.get_monthly_budget_cents(session)) == 0
    assert (await reimbursement_settings.get_default_cooldown_days(session)) == 7
    assert (await reimbursement_settings.get_reset_day(session)) == 1


@pytest.mark.asyncio
async def test_settings_round_trip(session):
    await reimbursement_settings.set_enabled(session, True)
    await reimbursement_settings.set_fixed_amount_cents(session, 5000)
    await reimbursement_settings.set_monthly_budget_cents(session, 500000)
    await reimbursement_settings.set_default_cooldown_days(session, 14)
    await reimbursement_settings.set_reset_day(session, 5)

    assert (await reimbursement_settings.is_enabled(session)) is True
    assert (await reimbursement_settings.get_fixed_amount_cents(session)) == 5000
    assert (await reimbursement_settings.get_monthly_budget_cents(session)) == 500000
    assert (await reimbursement_settings.get_default_cooldown_days(session)) == 14
    assert (await reimbursement_settings.get_reset_day(session)) == 5


@pytest.mark.asyncio
async def test_settings_clamp(session):
    # reset_day clamp 1-28
    await reimbursement_settings.set_reset_day(session, 99)
    assert (await reimbursement_settings.get_reset_day(session)) == 28
    await reimbursement_settings.set_reset_day(session, -1)
    assert (await reimbursement_settings.get_reset_day(session)) == 1
    # cooldown clamp 1-90
    await reimbursement_settings.set_default_cooldown_days(session, 999)
    assert (await reimbursement_settings.get_default_cooldown_days(session)) == 90
    await reimbursement_settings.set_default_cooldown_days(session, 0)
    assert (await reimbursement_settings.get_default_cooldown_days(session)) == 1
    # 金额/预算不可为负
    await reimbursement_settings.set_fixed_amount_cents(session, -100)
    assert (await reimbursement_settings.get_fixed_amount_cents(session)) == 0


def test_yuan_text_to_cents_parses():
    f = reimbursement_settings.yuan_text_to_cents
    assert f("50") == 5000
    assert f("50.5") == 5050
    assert f("50.00") == 5000
    assert f("1,000") == 100000
    with pytest.raises(ValueError):
        f("")
    with pytest.raises(ValueError):
        f("abc")
    with pytest.raises(ValueError):
        f("-10")


def test_cents_to_yuan_display():
    assert reimbursement_settings.cents_to_yuan_display(5000) == "50.00"
    assert reimbursement_settings.cents_to_yuan_display(123) == "1.23"


# ---------- eligibility_chat_repo ----------


@pytest.mark.asyncio
async def test_eligibility_add_list_remove(session):
    rows = await eligibility_chat_repo.list_active(session)
    assert rows == []
    e = await eligibility_chat_repo.create(
        session, telegram_chat_id=-1001, chat_type="channel", name="频道 A"
    )
    assert e.is_active is True
    assert (await eligibility_chat_repo.find_by_telegram_chat_id(session, -1001)).id == e.id

    await eligibility_chat_repo.deactivate(session, e)
    assert (await eligibility_chat_repo.list_active(session)) == []
    assert len(await eligibility_chat_repo.list_all(session)) == 1
    await eligibility_chat_repo.activate(session, e)
    assert len(await eligibility_chat_repo.list_active(session)) == 1


@pytest.mark.asyncio
async def test_eligibility_chat_id_is_unique(session):
    await eligibility_chat_repo.create(
        session, telegram_chat_id=-1002, chat_type="group", name="g1"
    )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await eligibility_chat_repo.create(
            session, telegram_chat_id=-1002, chat_type="group", name="dup"
        )


# ---------- reimbursement_override_repo ----------


@pytest.mark.asyncio
async def test_override_upsert_creates_then_updates(session):
    a = await reimbursement_override_repo.upsert(
        session, telegram_user_id=12345, cooldown_days=14, notes="vip", added_by=None
    )
    assert a.cooldown_days == 14
    b = await reimbursement_override_repo.upsert(
        session, telegram_user_id=12345, cooldown_days=3, notes="试用", added_by=None
    )
    assert b.id == a.id
    assert b.cooldown_days == 3
    assert b.notes == "试用"

    rows = await reimbursement_override_repo.list_all(session)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_override_find_and_remove(session):
    o = await reimbursement_override_repo.upsert(
        session, telegram_user_id=999, cooldown_days=21, notes=None, added_by=None
    )
    found = await reimbursement_override_repo.find_for_user(session, 999)
    assert found is not None and found.id == o.id

    await reimbursement_override_repo.remove(session, o)
    assert (await reimbursement_override_repo.find_for_user(session, 999)) is None


# ---------- reimbursement_repo（CRUD 基线） ----------


@pytest.mark.asyncio
async def test_create_wizard_request_baseline(session):
    app = await _seed_approved_application(session)
    r = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=app.applicant_telegram_id,
        applicant_username="u",
        applicant_display_name="U",
        application_id=app.id,
        amount_cents=5000,
    )
    assert r.status == REI_STATUS_WIZARD
    assert r.wizard_step == 1
    assert r.amount_cents == 5000

    active = await reimbursement_repo.get_active_for_user(session, app.applicant_telegram_id)
    assert active is not None and active.id == r.id


@pytest.mark.asyncio
async def test_submit_and_cancel_state_transitions(session):
    app = await _seed_approved_application(session)
    r = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=app.applicant_telegram_id,
        applicant_username=None,
        applicant_display_name=None,
        application_id=app.id,
        amount_cents=5000,
    )
    await reimbursement_repo.submit(session, r)
    assert r.status == REI_STATUS_PENDING
    assert r.submitted_at is not None

    # cancel
    await reimbursement_repo.cancel(session, r)
    assert r.status not in (REI_STATUS_PENDING, REI_STATUS_WIZARD)


@pytest.mark.asyncio
async def test_materials_add_and_clear(session):
    app = await _seed_approved_application(session)
    r = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=app.applicant_telegram_id,
        applicant_username=None,
        applicant_display_name=None,
        application_id=app.id,
        amount_cents=5000,
    )
    await reimbursement_repo.add_material(
        session,
        reimbursement_id=r.id,
        material_type=MAT_BOOKING,
        content_type="photo",
        telegram_file_id="fid1",
        text_content=None,
        original_message_id=10,
    )
    await reimbursement_repo.add_material(
        session,
        reimbursement_id=r.id,
        material_type=MAT_GESTURE,
        content_type="photo",
        telegram_file_id="fid2",
        text_content=None,
        original_message_id=11,
    )
    ms = await reimbursement_repo.list_materials(session, r.id)
    assert len(ms) == 2

    await reimbursement_repo.clear_materials(session, r.id)
    assert await reimbursement_repo.list_materials(session, r.id) == []


@pytest.mark.asyncio
async def test_list_pending_and_approved_unpaid(session):
    from datetime import datetime, timezone

    app1 = await _seed_approved_application(session, applicant_id=100)
    app2 = await _seed_approved_application(session, applicant_id=200)
    r1 = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=100,
        applicant_username=None,
        applicant_display_name=None,
        application_id=app1.id,
        amount_cents=5000,
    )
    r2 = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=200,
        applicant_username=None,
        applicant_display_name=None,
        application_id=app2.id,
        amount_cents=5000,
    )
    await reimbursement_repo.submit(session, r1)
    await reimbursement_repo.submit(session, r2)
    # 把 r2 改为 approved
    r2.status = REI_STATUS_APPROVED
    r2.reviewed_at = datetime.now(timezone.utc)
    await session.flush()

    pending = await reimbursement_repo.list_pending(session)
    assert {x.id for x in pending} == {r1.id}
    approved_unpaid = await reimbursement_repo.list_approved_unpaid(session)
    assert {x.id for x in approved_unpaid} == {r2.id}


@pytest.mark.asyncio
async def test_count_in_range_for_user(session):
    from datetime import datetime, timezone

    app = await _seed_approved_application(session, applicant_id=300)
    # 3 条 paid，1 条在范围外
    for d in (3, 5, 7):
        r = await reimbursement_repo.create_wizard(
            session,
            applicant_telegram_id=300,
            applicant_username=None,
            applicant_display_name=None,
            application_id=app.id,
            amount_cents=5000,
        )
        r.status = REI_STATUS_PAID
        r.reviewed_at = datetime(2026, 5, d, tzinfo=timezone.utc)
    await session.flush()

    n = await reimbursement_repo.count_in_range_for_user(
        session,
        applicant_telegram_id=300,
        start=datetime(2026, 5, 4, tzinfo=timezone.utc),
        end=datetime(2026, 5, 8, tzinfo=timezone.utc),
    )
    assert n == 2  # 5 号 + 7 号在范围内
