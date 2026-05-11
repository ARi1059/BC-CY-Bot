"""Wizard 状态机所有迁移路径的单元测试。"""

import pytest

from bccy_bot.db.models.enums import (
    APP_STATUS_CANCELLED,
    APP_STATUS_PENDING,
    APP_STATUS_WIZARD,
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REVIEW_MODE_SELF,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.repositories import application_repo
from bccy_bot.services import wizard_service
from bccy_bot.services.wizard_service import WizardError


# ---------- 数据准备 ----------


_DEFAULT_MATERIALS = [MAT_BOOKING, MAT_GESTURE, MAT_REPORT]


async def seed(session, *, materials=None, active: bool = True) -> tuple[Group, Inviter]:
    if materials is None:
        materials = _DEFAULT_MATERIALS
    grp = Group(telegram_chat_id=-100123, name="测试群")
    session.add(grp)
    await session.flush()
    inv = Inviter(
        telegram_user_id=999,
        display_name="张老师",
        group_label="A组",
        target_group_id=grp.id,
        required_materials=list(materials),
        review_mode=REVIEW_MODE_SELF,
        is_active=active,
    )
    session.add(inv)
    await session.flush()
    return grp, inv


# ---------- start_or_resume_application ----------


@pytest.mark.asyncio
async def test_start_creates_new_wizard(session):
    app = await wizard_service.start_or_resume_application(
        session, applicant_telegram_id=1, applicant_username="u", applicant_display_name="U"
    )
    assert app.status == APP_STATUS_WIZARD
    assert app.wizard_step == 0
    assert app.inviter_id is None


@pytest.mark.asyncio
async def test_start_resumes_existing_wizard(session):
    a1 = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    a2 = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    assert a1.id == a2.id


@pytest.mark.asyncio
async def test_start_blocked_by_pending(session):
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    app.status = APP_STATUS_PENDING
    await session.flush()
    with pytest.raises(WizardError):
        await wizard_service.start_or_resume_application(session, 1, "u", "U")


# ---------- select_inviter ----------


@pytest.mark.asyncio
async def test_select_inviter_advances_to_step_1(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    info = await wizard_service.select_inviter(session, app, inv.id)
    assert app.inviter_id == inv.id
    assert app.wizard_step == 1
    assert info.current_material_index == 0
    assert info.current_material_type == MAT_BOOKING
    assert info.expected_content_type == CT_PHOTO


@pytest.mark.asyncio
async def test_select_inactive_inviter_rejected(session):
    _, inv = await seed(session, active=False)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    with pytest.raises(WizardError):
        await wizard_service.select_inviter(session, app, inv.id)


@pytest.mark.asyncio
async def test_select_inviter_no_materials_configured_rejected(session):
    _, inv = await seed(session, materials=[])
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    with pytest.raises(WizardError):
        await wizard_service.select_inviter(session, app, inv.id)


# ---------- submit_material ----------


@pytest.mark.asyncio
async def test_submit_photo_advances(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)

    info = await wizard_service.submit_material(
        session, app,
        content_type=CT_PHOTO,
        media_group_id=None,
        telegram_file_id="photo-1",
        text_content=None,
        original_message_id=101,
    )
    assert app.wizard_step == 2
    assert info.current_material_type == MAT_GESTURE


@pytest.mark.asyncio
async def test_submit_rejects_media_group(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)

    with pytest.raises(WizardError, match="媒体组|打包"):
        await wizard_service.submit_material(
            session, app,
            content_type=CT_PHOTO,
            media_group_id="album-1",
            telegram_file_id="photo-1",
            text_content=None,
            original_message_id=101,
        )
    assert app.wizard_step == 1  # 未前进


@pytest.mark.asyncio
async def test_submit_wrong_content_type_rejected(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)

    # Step 1 期望 photo，但发了 text
    with pytest.raises(WizardError):
        await wizard_service.submit_material(
            session, app,
            content_type=CT_TEXT,
            media_group_id=None,
            telegram_file_id=None,
            text_content="some text",
            original_message_id=101,
        )
    assert app.wizard_step == 1


@pytest.mark.asyncio
async def test_full_three_step_submission(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)

    # 1: 约课记录 (photo)
    await wizard_service.submit_material(
        session, app, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="p1", text_content=None, original_message_id=101,
    )
    # 2: 上课手势 (photo)
    await wizard_service.submit_material(
        session, app, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="p2", text_content=None, original_message_id=102,
    )
    # 3: 出击报告 (text)
    info = await wizard_service.submit_material(
        session, app, content_type=CT_TEXT, media_group_id=None,
        telegram_file_id=None, text_content="今天出击 5 次", original_message_id=103,
    )
    assert info.is_preview is True
    assert app.wizard_step == 4

    materials = await application_repo.list_materials(session, app.id)
    assert [m.material_type for m in materials] == [MAT_BOOKING, MAT_GESTURE, MAT_REPORT]
    assert materials[0].telegram_file_id == "p1"
    assert materials[2].text_content == "今天出击 5 次"


# ---------- go_back ----------


@pytest.mark.asyncio
async def test_back_from_step_2_drops_last_material(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)
    await wizard_service.submit_material(
        session, app, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="p1", text_content=None, original_message_id=101,
    )
    assert app.wizard_step == 2

    info = await wizard_service.go_back(session, app)
    assert app.wizard_step == 1
    assert info.current_material_type == MAT_BOOKING

    materials = await application_repo.list_materials(session, app.id)
    assert materials == []  # 上一步的材料被删除


@pytest.mark.asyncio
async def test_back_from_step_1_returns_to_inviter_selection(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)
    assert app.wizard_step == 1

    info = await wizard_service.go_back(session, app)
    assert app.inviter_id is None
    assert app.wizard_step == 0
    assert info.is_inviter_selection is True


@pytest.mark.asyncio
async def test_back_from_preview_returns_to_last_material(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)
    for i in range(3):
        ct = CT_PHOTO if i < 2 else CT_TEXT
        await wizard_service.submit_material(
            session, app, content_type=ct, media_group_id=None,
            telegram_file_id=f"p{i}" if ct == CT_PHOTO else None,
            text_content="t" if ct == CT_TEXT else None,
            original_message_id=100 + i,
        )
    assert app.wizard_step == 4  # preview

    info = await wizard_service.go_back(session, app)
    assert app.wizard_step == 3
    assert info.current_material_type == MAT_REPORT
    assert info.is_preview is False


# ---------- confirm_submit / redo_materials ----------


@pytest.mark.asyncio
async def test_confirm_submit_marks_pending(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)
    for i in range(3):
        ct = CT_PHOTO if i < 2 else CT_TEXT
        await wizard_service.submit_material(
            session, app, content_type=ct, media_group_id=None,
            telegram_file_id=f"p{i}" if ct == CT_PHOTO else None,
            text_content="t" if ct == CT_TEXT else None,
            original_message_id=100 + i,
        )

    await wizard_service.confirm_submit(session, app)
    assert app.status == APP_STATUS_PENDING
    assert app.submitted_at is not None


@pytest.mark.asyncio
async def test_confirm_submit_rejected_when_not_preview(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)
    with pytest.raises(WizardError):
        await wizard_service.confirm_submit(session, app)


@pytest.mark.asyncio
async def test_redo_clears_materials_and_resets_step(session):
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.select_inviter(session, app, inv.id)
    for i in range(3):
        ct = CT_PHOTO if i < 2 else CT_TEXT
        await wizard_service.submit_material(
            session, app, content_type=ct, media_group_id=None,
            telegram_file_id=f"p{i}" if ct == CT_PHOTO else None,
            text_content="t" if ct == CT_TEXT else None,
            original_message_id=100 + i,
        )
    assert app.wizard_step == 4

    info = await wizard_service.redo_materials(session, app)
    assert app.wizard_step == 1
    materials = await application_repo.list_materials(session, app.id)
    assert materials == []
    assert info.current_material_type == MAT_BOOKING


# ---------- cancel ----------


@pytest.mark.asyncio
async def test_cancel_application_sets_status(session):
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.cancel_application(session, app)
    assert app.status == APP_STATUS_CANCELLED


@pytest.mark.asyncio
async def test_cancel_is_idempotent(session):
    app = await wizard_service.start_or_resume_application(session, 1, "u", "U")
    await wizard_service.cancel_application(session, app)
    await wizard_service.cancel_application(session, app)  # 第二次不抛
    assert app.status == APP_STATUS_CANCELLED


# ---------- 完整 happy path ----------


@pytest.mark.asyncio
async def test_full_happy_path(session):
    """选邀请人 → 提交 3 项 → 预览 → 确认 → pending。"""
    _, inv = await seed(session)
    app = await wizard_service.start_or_resume_application(session, 42, "neo", "Neo")
    await wizard_service.select_inviter(session, app, inv.id)

    await wizard_service.submit_material(
        session, app, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="booking", text_content=None, original_message_id=1,
    )
    await wizard_service.submit_material(
        session, app, content_type=CT_PHOTO, media_group_id=None,
        telegram_file_id="gesture", text_content=None, original_message_id=2,
    )
    info = await wizard_service.submit_material(
        session, app, content_type=CT_TEXT, media_group_id=None,
        telegram_file_id=None, text_content="出击报告全文", original_message_id=3,
    )
    assert info.is_preview is True

    await wizard_service.confirm_submit(session, app)
    assert app.status == APP_STATUS_PENDING
    assert app.applicant_username == "neo"
    materials = await application_repo.list_materials(session, app.id)
    assert len(materials) == 3
