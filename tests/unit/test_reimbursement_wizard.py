"""报销 wizard 状态机（v1.0.0-beta.3）：精简 precheck + 选老师 + 3 项材料 + 预览。"""

from datetime import datetime, timedelta, timezone

import pytest

from bccy_bot.db.models.enums import (
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REI_STATUS_APPROVED,
    REI_STATUS_PAID,
    REI_STATUS_PENDING,
    REI_STATUS_WIZARD,
)
from bccy_bot.db.models.reimburse_teacher import ReimburseTeacher
from bccy_bot.repositories import (
    reimburse_teacher_repo,
    reimbursement_override_repo,
    reimbursement_repo,
    reimbursement_settings,
)
from bccy_bot.services import reimbursement_wizard_service as rwz
from bccy_bot.services.reimbursement_wizard_service import ReimbursementWizardError


# ---------- 数据准备 ----------


async def _enable_reimbursement(session, *, budget=500000, remaining=500000, cd=7):
    await reimbursement_settings.set_enabled(session, True)
    await reimbursement_settings.set_monthly_budget_cents(session, budget)
    await reimbursement_settings.set_monthly_remaining_cents(session, remaining)
    await reimbursement_settings.set_default_cooldown_days(session, cd)


_uname_counter = 0


def _next_uname() -> str:
    global _uname_counter
    _uname_counter += 1
    return f"teacher_{_uname_counter}"


async def _seed_teacher(session, *, tier_cents: int = 10000) -> ReimburseTeacher:
    return await reimburse_teacher_repo.create(
        session,
        telegram_username=_next_uname(),
        display_name="T",
        group_label="A",
        reimbursement_tier_cents=tier_cents,
    )


# ---------- precheck ----------


@pytest.mark.asyncio
async def test_precheck_disabled_when_global_off(session):
    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.ok is False
    assert pre.reason_code == "disabled"


@pytest.mark.asyncio
async def test_precheck_disabled_when_budget_zero(session):
    await reimbursement_settings.set_enabled(session, True)
    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.reason_code == "disabled"


@pytest.mark.asyncio
async def test_precheck_does_not_require_approved_app(session):
    """v1.0.0-beta.3：报销与入群解耦，无需 approved 申请。"""
    await _enable_reimbursement(session)
    pre = await rwz.precheck(session, applicant_telegram_id=999)
    assert pre.ok is True
    assert pre.reason_code == "ok"


@pytest.mark.asyncio
async def test_precheck_has_active_pending(session):
    await _enable_reimbursement(session)
    r = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=100,
        applicant_username=None,
        applicant_display_name=None,
        amount_cents=10000,
    )
    r.status = REI_STATUS_PENDING
    r.submitted_at = datetime.now(timezone.utc)
    await session.flush()

    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.reason_code == "has_active_request"


@pytest.mark.asyncio
async def test_precheck_cooldown_uses_default_days(session):
    await _enable_reimbursement(session, cd=7)
    r = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=100,
        applicant_username=None,
        applicant_display_name=None,
        amount_cents=10000,
    )
    r.status = REI_STATUS_PAID
    r.reviewed_at = datetime.now(timezone.utc) - timedelta(days=2)
    await session.flush()

    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.reason_code == "cooldown"
    assert pre.cooldown_days_remaining is not None and pre.cooldown_days_remaining >= 4


@pytest.mark.asyncio
async def test_precheck_cooldown_uses_user_override(session):
    await _enable_reimbursement(session, cd=7)
    await reimbursement_override_repo.upsert(
        session, telegram_user_id=100, cooldown_days=3, notes=None, added_by=None
    )
    r = await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=100,
        applicant_username=None,
        applicant_display_name=None,
        amount_cents=10000,
    )
    r.status = REI_STATUS_APPROVED
    r.reviewed_at = datetime.now(timezone.utc) - timedelta(days=5)
    await session.flush()

    pre = await rwz.precheck(session, applicant_telegram_id=100)
    assert pre.ok is True


# ---------- create_request + set_teacher ----------


@pytest.mark.asyncio
async def test_create_request_starts_at_teacher_select_step(session):
    r = await rwz.create_request(
        session,
        applicant_telegram_id=100,
        applicant_username="u",
        applicant_display_name="U",
    )
    assert r.status == REI_STATUS_WIZARD
    assert r.wizard_step == rwz.TEACHER_STEP
    assert r.teacher_id is None
    assert r.amount_cents == 0

    info = rwz.resolve_step(r)
    assert info.is_teacher_select is True
    assert info.is_preview is False


@pytest.mark.asyncio
async def test_set_teacher_snapshots_amount_and_advances(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session, tier_cents=15000)
    r = await rwz.create_request(
        session,
        applicant_telegram_id=100,
        applicant_username="u",
        applicant_display_name=None,
    )
    teacher = await rwz.set_teacher(session, r, teacher_id=t.id)
    assert teacher.id == t.id
    assert r.teacher_id == t.id
    assert r.amount_cents == 15000
    assert r.teacher_username_snapshot == t.telegram_username
    assert r.wizard_step == rwz.FIRST_MATERIAL_STEP


@pytest.mark.asyncio
async def test_set_teacher_rejects_when_budget_insufficient(session):
    await _enable_reimbursement(session, budget=10000, remaining=3000)
    t = await _seed_teacher(session, tier_cents=10000)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    with pytest.raises(ReimbursementWizardError):
        await rwz.set_teacher(session, r, teacher_id=t.id)


@pytest.mark.asyncio
async def test_set_teacher_rejects_inactive(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    await reimburse_teacher_repo.toggle_active(session, t)  # 停用
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    with pytest.raises(ReimbursementWizardError):
        await rwz.set_teacher(session, r, teacher_id=t.id)


# ---------- 材料提交 ----------


@pytest.mark.asyncio
async def test_submit_material_rejected_in_teacher_select_step(session):
    await _enable_reimbursement(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    with pytest.raises(ReimbursementWizardError):
        await rwz.submit_material(
            session,
            r,
            content_type=CT_PHOTO,
            media_group_id=None,
            telegram_file_id="abc",
            text_content=None,
            original_message_id=1,
        )


@pytest.mark.asyncio
async def test_full_three_steps_to_preview(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    assert r.wizard_step == rwz.FIRST_MATERIAL_STEP

    # 1. 约课记录 (photo)
    info = await rwz.submit_material(
        session, r, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="f1", text_content=None, original_message_id=1,
    )
    assert info.current_material_type == MAT_GESTURE  # 已推进到下一项
    # 2. 上课手势 (photo)
    info = await rwz.submit_material(
        session, r, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="f2", text_content=None, original_message_id=2,
    )
    assert info.current_material_type == MAT_REPORT
    # 3. 出击报告 (text)
    info = await rwz.submit_material(
        session, r, content_type=CT_TEXT, media_group_id=None,
        telegram_file_id=None, text_content="ok", original_message_id=3,
    )
    assert info.is_preview is True


@pytest.mark.asyncio
async def test_submit_rejects_media_group(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    with pytest.raises(ReimbursementWizardError):
        await rwz.submit_material(
            session, r, content_type=CT_PHOTO, media_group_id="mg1",
            telegram_file_id="f", text_content=None, original_message_id=1,
        )


@pytest.mark.asyncio
async def test_submit_wrong_content_type(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    # 在等图片步骤却传文本
    with pytest.raises(ReimbursementWizardError):
        await rwz.submit_material(
            session, r, content_type=CT_TEXT, media_group_id=None,
            telegram_file_id=None, text_content="hello", original_message_id=1,
        )


# ---------- 回退 / 重做 / 确认 / 取消 ----------


@pytest.mark.asyncio
async def test_go_back_from_first_material_returns_to_teacher_select(session):
    """回退到 step 1 应清空已选老师与已传材料。"""
    await _enable_reimbursement(session)
    t = await _seed_teacher(session, tier_cents=15000)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    assert r.teacher_id == t.id

    info = await rwz.go_back(session, r)
    assert info.is_teacher_select is True
    assert r.teacher_id is None
    assert r.amount_cents == 0
    assert r.wizard_step == rwz.TEACHER_STEP


@pytest.mark.asyncio
async def test_go_back_from_middle_material_drops_last(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    await rwz.submit_material(
        session, r, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="f1", text_content=None, original_message_id=1,
    )
    # 现在在 step 3 (MAT_GESTURE)，已传 1 个
    info = await rwz.go_back(session, r)
    assert info.current_material_type == MAT_BOOKING
    mats = await reimbursement_repo.list_materials(session, r.id)
    assert len(mats) == 0


@pytest.mark.asyncio
async def test_go_back_from_preview_returns_to_last_material(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    for fid, ct in [("f1", CT_PHOTO), ("f2", CT_PHOTO)]:
        await rwz.submit_material(
            session, r, content_type=ct, media_group_id=None,
            telegram_file_id=fid, text_content=None, original_message_id=1,
        )
    await rwz.submit_material(
        session, r, content_type=CT_TEXT, media_group_id=None,
        telegram_file_id=None, text_content="ok", original_message_id=1,
    )
    info = await rwz.go_back(session, r)
    assert info.current_material_type == MAT_REPORT


@pytest.mark.asyncio
async def test_redo_clears_materials(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    for fid, ct in [("f1", CT_PHOTO), ("f2", CT_PHOTO)]:
        await rwz.submit_material(
            session, r, content_type=ct, media_group_id=None,
            telegram_file_id=fid, text_content=None, original_message_id=1,
        )
    await rwz.submit_material(
        session, r, content_type=CT_TEXT, media_group_id=None,
        telegram_file_id=None, text_content="ok", original_message_id=1,
    )
    # 现在在预览
    info = await rwz.redo_materials(session, r)
    assert info.current_material_type == MAT_BOOKING
    mats = await reimbursement_repo.list_materials(session, r.id)
    assert len(mats) == 0


@pytest.mark.asyncio
async def test_confirm_submit_marks_pending(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    for fid, ct in [("f1", CT_PHOTO), ("f2", CT_PHOTO)]:
        await rwz.submit_material(
            session, r, content_type=ct, media_group_id=None,
            telegram_file_id=fid, text_content=None, original_message_id=1,
        )
    await rwz.submit_material(
        session, r, content_type=CT_TEXT, media_group_id=None,
        telegram_file_id=None, text_content="ok", original_message_id=1,
    )
    await rwz.confirm_submit(session, r)
    assert r.status == REI_STATUS_PENDING
    assert r.submitted_at is not None


@pytest.mark.asyncio
async def test_confirm_rejected_when_not_in_preview(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    with pytest.raises(ReimbursementWizardError):
        await rwz.confirm_submit(session, r)


@pytest.mark.asyncio
async def test_cancel_idempotent(session):
    await _enable_reimbursement(session)
    t = await _seed_teacher(session)
    r = await rwz.create_request(
        session, applicant_telegram_id=100, applicant_username=None, applicant_display_name=None
    )
    await rwz.set_teacher(session, r, teacher_id=t.id)
    await rwz.cancel(session, r)
    # 再次取消不抛
    await rwz.cancel(session, r)
