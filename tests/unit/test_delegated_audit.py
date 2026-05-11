"""M3 代审型审核测试：广播 + 并发 + 差异化编辑。"""

from datetime import datetime, timezone

import pytest

from bccy_bot.db.models.admin import Admin
from bccy_bot.db.models.application import Application
from bccy_bot.db.models.application_material import ApplicationMaterial
from bccy_bot.db.models.audit_message import AuditMessage
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    APP_STATUS_PENDING,
    APP_STATUS_REJECTED,
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REVIEW_MODE_DELEGATED,
    ROLE_SUB,
    ROLE_SUPER,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.services import audit_service
from tests.unit.test_audit_service import FakeBot


async def _seed_delegated(session, admin_ids=(100, 200, 300)):
    """种入代审型场景：1 邀请人 + 多管理员 + 1 pending 申请 (含 photo+text 材料)。"""
    grp = Group(telegram_chat_id=-100123, name="测试群")
    session.add(grp)
    await session.flush()

    inv = Inviter(
        telegram_user_id=None,  # 代审型 inviter 可无 telegram_user_id
        display_name="王老师",
        group_label="B组",
        target_group_id=grp.id,
        required_materials=[MAT_BOOKING, MAT_GESTURE, MAT_REPORT],
        review_mode=REVIEW_MODE_DELEGATED,
        is_active=True,
    )
    session.add(inv)
    await session.flush()

    for i, tg_id in enumerate(admin_ids):
        session.add(
            Admin(
                telegram_user_id=tg_id,
                display_name=f"Admin{i}",
                role=ROLE_SUPER if i == 0 else ROLE_SUB,
                added_by=None,
            )
        )
    await session.flush()

    app = Application(
        applicant_telegram_id=42,
        applicant_username="apply_user",
        applicant_display_name="申请人",
        inviter_id=inv.id,
        status=APP_STATUS_PENDING,
        wizard_step=0,
        submitted_at=datetime(2026, 5, 12, 14, 23, tzinfo=timezone.utc),
    )
    session.add(app)
    await session.flush()

    for i, (mt, ct, tag) in enumerate([
        (MAT_BOOKING, CT_PHOTO, "booking-fid"),
        (MAT_GESTURE, CT_PHOTO, "gesture-fid"),
        (MAT_REPORT, CT_TEXT, "代审场景测试"),
    ]):
        session.add(
            ApplicationMaterial(
                application_id=app.id,
                material_type=mt,
                content_type=ct,
                telegram_file_id=tag if ct == CT_PHOTO else None,
                text_content=tag if ct == CT_TEXT else None,
                original_message_id=100 + i,
            )
        )
    await session.flush()
    return app, inv, list(admin_ids)


# ---------- 广播 ----------


@pytest.mark.asyncio
async def test_notify_delegated_broadcasts_to_every_admin(session):
    bot = FakeBot()
    app, _, admin_ids = await _seed_delegated(session)

    await audit_service.notify_reviewers(session, bot, app)

    # 3 个管理员各收到 1 媒体组 + 1 文本+按钮
    assert len(bot.sent_media) == 3
    assert {m.chat_id for m in bot.sent_media} == set(admin_ids)
    assert len(bot.sent_texts) == 3
    assert {t.chat_id for t in bot.sent_texts} == set(admin_ids)

    # audit_messages 表 3 行（每管理员一行）
    from sqlalchemy import select

    rows = (await session.execute(select(AuditMessage))).scalars().all()
    assert len(rows) == 3
    assert {r.reviewer_telegram_id for r in rows} == set(admin_ids)


@pytest.mark.asyncio
async def test_notify_delegated_with_no_admins_is_safe(session):
    bot = FakeBot()
    app, _, _ = await _seed_delegated(session, admin_ids=())

    await audit_service.notify_reviewers(session, bot, app)

    assert bot.sent_media == []
    assert bot.sent_texts == []


# ---------- 通过 + 差异化编辑 ----------


@pytest.mark.asyncio
async def test_approve_in_delegated_edits_acting_and_others_differently(session):
    bot = FakeBot()
    app, _, admin_ids = await _seed_delegated(session)
    await audit_service.notify_reviewers(session, bot, app)

    acting_admin = admin_ids[1]  # 中间的管理员操作
    await audit_service.approve_application(
        session,
        bot,
        app,
        reviewer_telegram_id=acting_admin,
        reviewer_role="admin",
        reviewer_display="@admin_acting",
    )

    assert app.status == APP_STATUS_APPROVED

    # 3 条 audit_message 都被编辑
    assert len(bot.edited) == 3

    edits_by_chat = {e.chat_id: e.text for e in bot.edited}
    # acting 看到 ✅ 已通过
    assert "已通过" in edits_by_chat[acting_admin]
    assert "@admin_acting" in edits_by_chat[acting_admin]
    # 其他两位看到 ⏩ 已被处理
    for other in admin_ids:
        if other == acting_admin:
            continue
        assert "已被" in edits_by_chat[other]
        assert "@admin_acting" in edits_by_chat[other]
        assert "已通过" not in edits_by_chat[other]


@pytest.mark.asyncio
async def test_reject_in_delegated_edits_acting_and_others_differently(session):
    bot = FakeBot()
    app, _, admin_ids = await _seed_delegated(session)
    await audit_service.notify_reviewers(session, bot, app)

    await audit_service.reject_application(
        session, bot, app,
        reviewer_telegram_id=admin_ids[0],
        reviewer_role="admin",
        reason="材料不符",
        reviewer_display="@admin0",
    )
    assert app.status == APP_STATUS_REJECTED

    edits_by_chat = {e.chat_id: e.text for e in bot.edited}
    assert "已拒绝" in edits_by_chat[admin_ids[0]]
    assert "材料不符" in edits_by_chat[admin_ids[0]]
    for other in admin_ids[1:]:
        assert "已被" in edits_by_chat[other]
        assert "材料不符" not in edits_by_chat[other]  # 拒绝原因不外泄给其他管理员


# ---------- 并发竞态：第二个审核者读到 status != pending 即拒绝 ----------


@pytest.mark.asyncio
async def test_second_approve_after_first_commits_is_rejected(session):
    """
    模拟两个管理员先后操作同一申请。
    第一个 approve 成功；第二个再调 approve 时 application.status='approved'，应抛 AuditError。
    """
    bot = FakeBot()
    app, _, admin_ids = await _seed_delegated(session)

    await audit_service.approve_application(
        session, bot, app,
        reviewer_telegram_id=admin_ids[0],
        reviewer_role="admin",
        reviewer_display="@a0",
    )
    assert app.status == APP_STATUS_APPROVED

    with pytest.raises(audit_service.AuditError):
        await audit_service.approve_application(
            session, bot, app,
            reviewer_telegram_id=admin_ids[1],
            reviewer_role="admin",
            reviewer_display="@a1",
        )


@pytest.mark.asyncio
async def test_second_reject_after_first_approve_is_rejected(session):
    bot = FakeBot()
    app, _, admin_ids = await _seed_delegated(session)

    await audit_service.approve_application(
        session, bot, app,
        reviewer_telegram_id=admin_ids[0],
        reviewer_role="admin",
        reviewer_display="@a0",
    )
    with pytest.raises(audit_service.AuditError):
        await audit_service.reject_application(
            session, bot, app,
            reviewer_telegram_id=admin_ids[1],
            reviewer_role="admin",
            reason="reason",
            reviewer_display="@a1",
        )


# ---------- 行锁字段 locked_by ----------


@pytest.mark.asyncio
async def test_load_pending_with_lock_marks_locked_by(session_factory):
    """直接验证 _load_pending_with_lock 写入 locked_by。"""
    from bccy_bot.handlers.inviter.audit import _load_pending_with_lock

    async with session_factory() as s1:
        app, _, admin_ids = await _seed_delegated(s1)
        await s1.commit()
        app_id = app.id

    async with session_factory() as s2:
        locked_app = await _load_pending_with_lock(s2, app_id, admin_ids[0])
        assert locked_app is not None
        assert locked_app.locked_by == admin_ids[0]
        await s2.commit()


@pytest.mark.asyncio
async def test_load_pending_after_approval_returns_none(session_factory):
    """已被处理的申请，load_pending_with_lock 返回 None。"""
    from bccy_bot.handlers.inviter.audit import _load_pending_with_lock

    bot = FakeBot()
    async with session_factory() as s1:
        app, _, admin_ids = await _seed_delegated(s1)
        await audit_service.approve_application(
            s1, bot, app,
            reviewer_telegram_id=admin_ids[0],
            reviewer_role="admin",
            reviewer_display="@a0",
        )
        await s1.commit()
        app_id = app.id

    async with session_factory() as s2:
        locked_app = await _load_pending_with_lock(s2, app_id, admin_ids[1])
        assert locked_app is None  # 已 approved，second admin 拿不到


# ---------- _authorize ----------


@pytest.mark.asyncio
async def test_authorize_admin_for_delegated_inviter(session):
    from bccy_bot.handlers.inviter.audit import _authorize

    app, _, admin_ids = await _seed_delegated(session)

    ok, role = await _authorize(session, app, admin_ids[0])
    assert ok is True and role == "admin"

    # 非管理员的随机用户：拒绝
    ok, role = await _authorize(session, app, 9999)
    assert ok is False and role == "admin"


@pytest.mark.asyncio
async def test_authorize_self_review_unchanged(session):
    """自审型分支授权不受 M3 影响。"""
    from bccy_bot.handlers.inviter.audit import _authorize
    from bccy_bot.db.models.enums import REVIEW_MODE_SELF

    grp = Group(telegram_chat_id=-100123, name="g")
    session.add(grp)
    await session.flush()
    inv = Inviter(
        telegram_user_id=777,
        display_name="X",
        group_label="A",
        target_group_id=grp.id,
        required_materials=[MAT_REPORT],
        review_mode=REVIEW_MODE_SELF,
        is_active=True,
    )
    session.add(inv)
    await session.flush()
    app = Application(
        applicant_telegram_id=1,
        inviter_id=inv.id,
        status=APP_STATUS_PENDING,
        wizard_step=0,
    )
    session.add(app)
    await session.flush()

    ok, role = await _authorize(session, app, 777)
    assert ok and role == "inviter"

    ok, role = await _authorize(session, app, 999)
    assert not ok and role == "inviter"
