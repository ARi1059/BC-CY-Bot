"""M12 报销 wizard：4 层预校验 + 状态机 + 媒体组拒收 + 类型错配。"""

from datetime import datetime, timedelta, timezone

import pytest

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    APP_STATUS_PENDING,
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REI_STATUS_APPROVED,
    REI_STATUS_PAID,
    REI_STATUS_PENDING,
    REI_STATUS_WIZARD,
    REVIEW_MODE_SELF,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.repositories import (
    reimbursement_override_repo,
    reimbursement_repo,
    reimbursement_settings,
)
from bccy_bot.services import reimbursement_wizard_service as rwz


# ---------- 数据准备 ----------


_chat_counter = -100500


def _next_chat_id() -> int:
    global _chat_counter
    _chat_counter -= 1
    return _chat_counter


async def _seed_approved_app(session, applicant_id: int = 100) -> Application:
    g = Group(telegram_chat_id=_next_chat_id(), name="g")
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
        reviewed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),  # 老到不会触发冷却
    )
    session.add(app)
    await session.flush()
    return app


async def _enable_reimbursement(session, *, amount=5000, budget=500000, remaining=500000, cd=7):
    await reimbursement_settings.set_enabled(session, True)
    await reimbursement_settings.set_fixed_amount_cents(session, amount)
    await reimbursement_settings.set_monthly_budget_cents(session, budget)
    await reimbursement_settings.set_monthly_remaining_cents(session, remaining)
    await reimbursement_settings.set_default_cooldown_days(session, cd)


# ---------- 预校验 ----------


@pytest.mark.asyncio
async def test_precheck_disabled_when_global_off(session):
    await _seed_approved_app(session)
    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.ok is False
    assert pre.reason_code == "disabled"


@pytest.mark.asyncio
async def test_precheck_disabled_when_amount_zero(session):
    await _seed_approved_app(session)
    await reimbursement_settings.set_enabled(session, True)
    # amount = 0
    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.reason_code == "disabled"


@pytest.mark.asyncio
async def test_precheck_no_approved_app(session):
    await _enable_reimbursement(session)
    pre = await rwz.precheck(session, applicant_telegram_id=999)
    assert pre.reason_code == "no_approved_app"


@pytest.mark.asyncio
async def test_precheck_has_active_pending(session):
    """已有 pending 报销 → has_active_request。"""
    app = await _seed_approved_app(session)
    await _enable_reimbursement(session)
    r = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=app.applicant_telegram_id,
        applicant_username=None,
        applicant_display_name=None,
        application_id=app.id,
        amount_cents=5000,
    )
    r.status = REI_STATUS_PENDING
    r.submitted_at = datetime.now(timezone.utc)
    await session.flush()

    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.reason_code == "has_active_request"


@pytest.mark.asyncio
async def test_precheck_cooldown_uses_default_days(session):
    app = await _seed_approved_app(session)
    await _enable_reimbursement(session, cd=7)
    # 已有上次报销 reviewed_at 2 天前 → 还差 5 天
    r = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=app.applicant_telegram_id,
        applicant_username=None,
        applicant_display_name=None,
        application_id=app.id,
        amount_cents=5000,
    )
    r.status = REI_STATUS_PAID
    r.reviewed_at = datetime.now(timezone.utc) - timedelta(days=2)
    await session.flush()

    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.reason_code == "cooldown"
    assert pre.cooldown_days_remaining is not None and pre.cooldown_days_remaining >= 4


@pytest.mark.asyncio
async def test_precheck_cooldown_uses_user_override(session):
    app = await _seed_approved_app(session)
    await _enable_reimbursement(session, cd=7)
    # 全局 7 天，但该用户覆盖为 3 天；上次 5 天前 → 通过
    await reimbursement_override_repo.upsert(
        session, telegram_user_id=100, cooldown_days=3, notes=None, added_by=None
    )
    r = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=app.applicant_telegram_id,
        applicant_username=None,
        applicant_display_name=None,
        application_id=app.id,
        amount_cents=5000,
    )
    r.status = REI_STATUS_APPROVED
    r.reviewed_at = datetime.now(timezone.utc) - timedelta(days=5)
    await session.flush()

    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.ok is True


@pytest.mark.asyncio
async def test_precheck_budget_insufficient(session):
    await _seed_approved_app(session)
    # 余额 30 元，固定金额 50 元 → 不足
    await _enable_reimbursement(session, amount=5000, budget=10000, remaining=3000)
    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.reason_code == "budget_insufficient"


@pytest.mark.asyncio
async def test_precheck_ok_path(session):
    await _seed_approved_app(session)
    await _enable_reimbursement(session)
    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.ok is True
    assert pre.application_id is not None
    assert pre.fixed_amount_cents == 5000


# ---------- Wizard 状态机 ----------


async def _make_wizard(session) -> tuple:
    app = await _seed_approved_app(session)
    await _enable_reimbursement(session)
    r = await rwz.create_request(
        session,
        applicant_telegram_id=app.applicant_telegram_id,
        applicant_username="u",
        applicant_display_name="U",
        application_id=app.id,
        fixed_amount_cents=5000,
    )
    return app, r


@pytest.mark.asyncio
async def test_create_request_starts_at_step_1(session):
    _, r = await _make_wizard(session)
    assert r.status == REI_STATUS_WIZARD
    assert r.wizard_step == 1
    info = rwz.resolve_step(r)
    assert info.current_material_type == MAT_BOOKING
    assert info.expected_content_type == CT_PHOTO


@pytest.mark.asyncio
async def test_submit_photo_advances(session):
    _, r = await _make_wizard(session)
    info = await rwz.submit_material(
        session, r,
        content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="p1", text_content=None, original_message_id=100,
    )
    assert r.wizard_step == 2
    assert info.current_material_type == MAT_GESTURE


@pytest.mark.asyncio
async def test_submit_rejects_media_group(session):
    _, r = await _make_wizard(session)
    with pytest.raises(rwz.ReimbursementWizardError, match="媒体组|打包"):
        await rwz.submit_material(
            session, r,
            content_type=CT_PHOTO, media_group_id="album-1",
            telegram_file_id="p1", text_content=None, original_message_id=100,
        )
    assert r.wizard_step == 1


@pytest.mark.asyncio
async def test_submit_wrong_content_type(session):
    _, r = await _make_wizard(session)
    # 第 1 步期望 photo，发了 text
    with pytest.raises(rwz.ReimbursementWizardError):
        await rwz.submit_material(
            session, r,
            content_type=CT_TEXT, media_group_id=None,
            telegram_file_id=None, text_content="hi", original_message_id=100,
        )
    assert r.wizard_step == 1


@pytest.mark.asyncio
async def test_full_three_step_then_preview(session):
    _, r = await _make_wizard(session)
    await rwz.submit_material(
        session, r, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="p1", text_content=None, original_message_id=1,
    )
    await rwz.submit_material(
        session, r, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="p2", text_content=None, original_message_id=2,
    )
    info = await rwz.submit_material(
        session, r, content_type=CT_TEXT, media_group_id=None,
        telegram_file_id=None, text_content="出击 3 次", original_message_id=3,
    )
    assert info.is_preview is True
    assert r.wizard_step == 4


@pytest.mark.asyncio
async def test_back_from_step_2_removes_last_material(session):
    _, r = await _make_wizard(session)
    await rwz.submit_material(
        session, r, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="p1", text_content=None, original_message_id=1,
    )
    assert r.wizard_step == 2

    info = await rwz.go_back(session, r)
    assert r.wizard_step == 1
    assert info.current_material_type == MAT_BOOKING
    ms = await reimbursement_repo.list_materials(session, r.id)
    assert ms == []


@pytest.mark.asyncio
async def test_back_from_preview_returns_to_step_3(session):
    _, r = await _make_wizard(session)
    for i, (ct, fid, tx) in enumerate([
        (CT_PHOTO, "p1", None),
        (CT_PHOTO, "p2", None),
        (CT_TEXT, None, "report"),
    ]):
        await rwz.submit_material(
            session, r, content_type=ct, media_group_id=None,
            telegram_file_id=fid, text_content=tx, original_message_id=10 + i,
        )
    assert r.wizard_step == 4

    info = await rwz.go_back(session, r)
    assert r.wizard_step == 3
    assert info.current_material_type == MAT_REPORT


@pytest.mark.asyncio
async def test_redo_clears_materials(session):
    _, r = await _make_wizard(session)
    for i, (ct, fid, tx) in enumerate([
        (CT_PHOTO, "p1", None),
        (CT_PHOTO, "p2", None),
        (CT_TEXT, None, "report"),
    ]):
        await rwz.submit_material(
            session, r, content_type=ct, media_group_id=None,
            telegram_file_id=fid, text_content=tx, original_message_id=10 + i,
        )

    info = await rwz.redo_materials(session, r)
    assert r.wizard_step == 1
    assert info.current_material_type == MAT_BOOKING
    assert (await reimbursement_repo.list_materials(session, r.id)) == []


@pytest.mark.asyncio
async def test_confirm_submit_marks_pending(session):
    _, r = await _make_wizard(session)
    for i, (ct, fid, tx) in enumerate([
        (CT_PHOTO, "p1", None),
        (CT_PHOTO, "p2", None),
        (CT_TEXT, None, "report"),
    ]):
        await rwz.submit_material(
            session, r, content_type=ct, media_group_id=None,
            telegram_file_id=fid, text_content=tx, original_message_id=10 + i,
        )

    await rwz.confirm_submit(session, r)
    assert r.status == REI_STATUS_PENDING
    assert r.submitted_at is not None


@pytest.mark.asyncio
async def test_confirm_rejected_when_not_in_preview(session):
    _, r = await _make_wizard(session)
    with pytest.raises(rwz.ReimbursementWizardError):
        await rwz.confirm_submit(session, r)


@pytest.mark.asyncio
async def test_cancel_idempotent(session):
    _, r = await _make_wizard(session)
    await rwz.cancel(session, r)
    await rwz.cancel(session, r)  # 不抛
