"""M13 报销审核 + 口令转发 + 多管理员并发。"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from bccy_bot.db.models.admin import Admin
from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REI_STATUS_APPROVED,
    REI_STATUS_PAID,
    REI_STATUS_PENDING,
    REI_STATUS_REJECTED,
    REVIEW_MODE_SELF,
    ROLE_SUB,
    ROLE_SUPER,
    SK_LOG_CHANNEL_ID,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.db.models.reimbursement_audit_message import ReimbursementAuditMessage
from bccy_bot.db.models.reimbursement_material import ReimbursementMaterial
from bccy_bot.db.models.reimbursement_request import ReimbursementRequest
from bccy_bot.repositories import reimbursement_settings, settings_repo
from bccy_bot.services import reimbursement_audit_service as audit
from tests.unit.test_audit_service import FakeBot


# ---------- seeds ----------


_chat = -100700


def _next_chat() -> int:
    global _chat
    _chat -= 1
    return _chat


async def _seed_pending(
    session,
    *,
    applicant_id: int = 100,
    amount_cents: int = 5000,
    admin_ids: tuple[int, ...] = (200, 300, 400),
) -> tuple[ReimbursementRequest, list[int]]:
    """注入：管理员若干 + 1 个 approved 申请 + 1 个 pending 报销 + 3 项材料。"""
    g = Group(telegram_chat_id=_next_chat(), name="g")
    session.add(g)
    await session.flush()
    inv = Inviter(
        telegram_user_id=999,
        display_name="x",
            target_group_id=g.id,
        required_materials=[MAT_REPORT],
        review_mode=REVIEW_MODE_SELF,
        is_active=True,
    )
    session.add(inv)
    await session.flush()
    app = Application(
        applicant_telegram_id=applicant_id,
        applicant_username="alice",
        inviter_id=inv.id,
        status=APP_STATUS_APPROVED,
        wizard_step=0,
        reviewed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    session.add(app)
    await session.flush()
    for i, tg in enumerate(admin_ids):
        session.add(
            Admin(
                telegram_user_id=tg,
                display_name=f"adm{i}",
                role=ROLE_SUPER if i == 0 else ROLE_SUB,
                added_by=None,
            )
        )
    await session.flush()
    r = ReimbursementRequest(
        applicant_telegram_id=applicant_id,
        applicant_username="alice",
            status=REI_STATUS_PENDING,
        wizard_step=0,
        amount_cents=amount_cents,
        submitted_at=datetime(2026, 5, 12, 14, 0, tzinfo=timezone.utc),
    )
    session.add(r)
    await session.flush()
    for i, (mt, ct, tag) in enumerate(
        [
            (MAT_BOOKING, CT_PHOTO, "booking-fid"),
            (MAT_GESTURE, CT_PHOTO, "gesture-fid"),
            (MAT_REPORT, CT_TEXT, "本周出击 3 次成功"),
        ]
    ):
        session.add(
            ReimbursementMaterial(
                reimbursement_id=r.id,
                material_type=mt,
                content_type=ct,
                telegram_file_id=tag if ct == CT_PHOTO else None,
                text_content=tag if ct == CT_TEXT else None,
                original_message_id=100 + i,
            )
        )
    await session.flush()
    return r, list(admin_ids)


# ---------- notify_admins ----------


@pytest.mark.asyncio
async def test_notify_broadcasts_to_every_admin(session):
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session)

    await audit.notify_admins(session, bot, r)

    # 每位 admin 都收到 1 媒体组 + 1 文本+按钮
    assert len(bot.sent_media) == 3
    assert {m.chat_id for m in bot.sent_media} == set(admin_ids)
    assert len(bot.sent_texts) == 3
    assert {t.chat_id for t in bot.sent_texts} == set(admin_ids)

    rows = (await session.execute(select(ReimbursementAuditMessage))).scalars().all()
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_notify_safe_when_no_admins(session):
    bot = FakeBot()
    r, _ = await _seed_pending(session, admin_ids=())
    await audit.notify_admins(session, bot, r)
    assert bot.sent_media == []
    assert bot.sent_texts == []


@pytest.mark.asyncio
async def test_notify_emits_log_channel_event_when_bound(session):
    await settings_repo.set_value(session, SK_LOG_CHANNEL_ID, "-1001999999")
    bot = FakeBot()
    r, _ = await _seed_pending(session)
    await audit.notify_admins(session, bot, r)
    # 日志频道收到 1 条文本（new 卡片）+ 每位 admin 1 条；总共 >= 1 + 3
    log_texts = [t for t in bot.sent_texts if t.chat_id == -1001999999]
    assert len(log_texts) == 1
    assert "新报销申请" in log_texts[0].text


# ---------- approve + payment ----------


@pytest.mark.asyncio
async def test_approve_then_pay_full_flow(session):
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session)
    # 月预算 500 元，需扣 50 元
    await reimbursement_settings.set_monthly_budget_cents(session, 50000)
    await reimbursement_settings.set_monthly_remaining_cents(session, 50000)

    await audit.notify_admins(session, bot, r)
    initial_text_count = len(bot.sent_texts)

    intent = await audit.approve_request_step1(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@admin0",
    )
    assert intent.reimbursement_id == r.id
    assert r.status == REI_STATUS_APPROVED
    assert (await reimbursement_settings.get_monthly_remaining_cents(session)) == 45000

    # 审核消息已被编辑
    edited_after_approve = list(bot.edited)
    assert len(edited_after_approve) == 3
    assert any("已通过" in e.text and "待付款" in e.text for e in edited_after_approve)

    # 第二阶段：确认付款
    await audit.confirm_payment(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@admin0",
        payment_code_text="阿里贝贝出击成功",
    )
    assert r.status == REI_STATUS_PAID
    assert r.alipay_code_text == "阿里贝贝出击成功"
    assert r.paid_at is not None
    assert r.paid_by_telegram_id == admin_ids[0]

    # 申请人收到口令消息
    applicant_msgs = [t for t in bot.sent_texts if t.chat_id == r.applicant_telegram_id]
    assert any("阿里贝贝出击成功" in t.text for t in applicant_msgs)


@pytest.mark.asyncio
async def test_approve_with_insufficient_budget_auto_rejects(session):
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session, amount_cents=10000)
    # 仅 30 元余额，需 100 元 → 自动 reject
    await reimbursement_settings.set_monthly_remaining_cents(session, 3000)
    await audit.notify_admins(session, bot, r)

    with pytest.raises(audit.ReimbursementAuditError, match="预算"):
        await audit.approve_request_step1(
            session, bot, r,
            reviewer_telegram_id=admin_ids[0],
            reviewer_display="@admin0",
        )
    assert r.status == REI_STATUS_REJECTED
    # 余额未被扣减
    assert (await reimbursement_settings.get_monthly_remaining_cents(session)) == 3000


# ---------- reject ----------


@pytest.mark.asyncio
async def test_reject_with_reason(session):
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session)
    await audit.notify_admins(session, bot, r)

    await audit.reject_request(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@admin0",
        reason="材料不全",
    )
    assert r.status == REI_STATUS_REJECTED
    assert r.reject_reason == "材料不全"

    # 申请人收到拒绝消息
    applicant_msgs = [t for t in bot.sent_texts if t.chat_id == r.applicant_telegram_id]
    assert any("未通过" in t.text and "材料不全" in t.text for t in applicant_msgs)

    # 审核消息已编辑：acting 看到原因，其他 admin 看到"已被处理"
    edits = {e.chat_id: e.text for e in bot.edited}
    assert "已拒绝" in edits[admin_ids[0]]
    assert "材料不全" in edits[admin_ids[0]]
    for other in admin_ids[1:]:
        assert "已被" in edits[other]
        assert "材料不全" not in edits[other]  # 原因不外泄


@pytest.mark.asyncio
async def test_reject_without_reason(session):
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session)
    await audit.reject_request(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@admin0",
        reason=None,
    )
    assert r.status == REI_STATUS_REJECTED
    assert r.reject_reason is None


# ---------- 并发竞态：第二个 approve 拒绝 ----------


@pytest.mark.asyncio
async def test_second_approve_after_first_is_rejected(session):
    """sequential simulation：第一管理员通过后，第二个再点通过应抛错。"""
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session)
    await reimbursement_settings.set_monthly_remaining_cents(session, 50000)

    await audit.approve_request_step1(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@a0",
    )
    assert r.status == REI_STATUS_APPROVED

    with pytest.raises(audit.ReimbursementAuditError):
        await audit.approve_request_step1(
            session, bot, r,
            reviewer_telegram_id=admin_ids[1],
            reviewer_display="@a1",
        )


# ---------- confirm_payment 边界 ----------


@pytest.mark.asyncio
async def test_confirm_payment_rejects_when_not_approved(session):
    bot = FakeBot()
    r, _ = await _seed_pending(session)
    # 仍在 pending 状态时直接调 confirm_payment → 抛错
    with pytest.raises(audit.ReimbursementAuditError):
        await audit.confirm_payment(
            session, bot, r,
            reviewer_telegram_id=200,
            reviewer_display="@x",
            payment_code_text="anything",
        )


@pytest.mark.asyncio
async def test_confirm_payment_rejects_empty_code(session):
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session)
    await reimbursement_settings.set_monthly_remaining_cents(session, 50000)
    await audit.approve_request_step1(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@a0",
    )
    with pytest.raises(audit.ReimbursementAuditError):
        await audit.confirm_payment(
            session, bot, r,
            reviewer_telegram_id=admin_ids[0],
            reviewer_display="@a0",
            payment_code_text="   ",
        )
    # 状态仍是 approved，未变成 paid
    assert r.status == REI_STATUS_APPROVED


# ---------- v1.0.0-beta.4 口令发放员 + 行内代码 ----------


@pytest.mark.asyncio
async def test_approve_dispatches_to_relay_user_when_configured(session):
    """配置口令发放员后，approve_step1 应 DM 该用户并返回 relay_dispatched=True。"""
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session)
    await reimbursement_settings.set_monthly_budget_cents(session, 50000)
    await reimbursement_settings.set_monthly_remaining_cents(session, 50000)
    await reimbursement_settings.set_payment_relay_telegram_id(session, 88888)

    await audit.notify_admins(session, bot, r)

    intent = await audit.approve_request_step1(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@admin0",
    )
    assert intent.relay_dispatched is True
    assert intent.relay_user_id == 88888

    # 88888 应收到 DM 包含审核摘要 + 按钮
    relay_dms = [t for t in bot.sent_texts if t.chat_id == 88888]
    assert len(relay_dms) >= 1
    assert any("待发放报销" in t.text for t in relay_dms)
    assert relay_dms[-1].reply_markup is not None  # 含 [🧧 输入口令] 按钮


@pytest.mark.asyncio
async def test_approve_falls_back_when_relay_not_configured(session):
    """未配置口令发放员（默认 0）→ relay_dispatched=False，沿用原审核者输入路径。"""
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session)
    await reimbursement_settings.set_monthly_budget_cents(session, 50000)
    await reimbursement_settings.set_monthly_remaining_cents(session, 50000)
    # 不设置 payment_relay → 默认 0

    await audit.notify_admins(session, bot, r)
    intent = await audit.approve_request_step1(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@admin0",
    )
    assert intent.relay_dispatched is False
    assert intent.relay_user_id is None


@pytest.mark.asyncio
async def test_approve_falls_back_when_relay_dm_fails(session):
    """配置了 relay 但 DM 失败（如用户没私聊过 Bot）→ fallback 到审核者。"""
    from telegram.error import Forbidden

    bot = FakeBot()
    # 让 FakeBot 在 send_message 给 99999 时抛错
    original = bot.send_message

    async def failing_send(chat_id, text, reply_markup=None, **kwargs):
        if chat_id == 99999:
            raise Forbidden("bot blocked by user")
        return await original(chat_id, text, reply_markup, **kwargs)
    bot.send_message = failing_send

    r, admin_ids = await _seed_pending(session)
    await reimbursement_settings.set_monthly_budget_cents(session, 50000)
    await reimbursement_settings.set_monthly_remaining_cents(session, 50000)
    await reimbursement_settings.set_payment_relay_telegram_id(session, 99999)

    await audit.notify_admins(session, bot, r)
    intent = await audit.approve_request_step1(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@admin0",
    )
    assert intent.relay_dispatched is False  # fallback


@pytest.mark.asyncio
async def test_confirm_payment_sends_inline_code_to_applicant(session):
    """v1.0.0-beta.4：发给申请人的口令消息应包含 <code>...</code> 行内代码。"""
    bot = FakeBot()
    r, admin_ids = await _seed_pending(session)
    await reimbursement_settings.set_monthly_budget_cents(session, 50000)
    await reimbursement_settings.set_monthly_remaining_cents(session, 50000)
    await audit.notify_admins(session, bot, r)
    await audit.approve_request_step1(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@admin0",
    )

    code = "口令A&B<x>"  # 含 HTML 特殊字符，验证 escape
    await audit.confirm_payment(
        session, bot, r,
        reviewer_telegram_id=admin_ids[0],
        reviewer_display="@admin0",
        payment_code_text=code,
    )

    applicant_msgs = [t for t in bot.sent_texts if t.chat_id == r.applicant_telegram_id]
    assert applicant_msgs, "applicant should receive DM"
    last_text = applicant_msgs[-1].text
    assert "<code>" in last_text and "</code>" in last_text
    # HTML 实体已转义
    assert "&amp;" in last_text
    assert "&lt;" in last_text and "&gt;" in last_text
