"""M14 报销报表生成 + 月预算重置。"""

from datetime import datetime, timezone

import pytest

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    MAT_REPORT,
    REI_STATUS_PAID,
    REI_STATUS_PENDING,
    REI_STATUS_REJECTED,
    REVIEW_MODE_SELF,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.db.models.reimbursement_request import ReimbursementRequest
from bccy_bot.repositories import reimbursement_settings
from bccy_bot.services import reimbursement_reports_service as reports


_chat = -100900


def _next_chat() -> int:
    global _chat
    _chat -= 1
    return _chat


async def _seed_inviter_app(session) -> Application:
    g = Group(telegram_chat_id=_next_chat(), name="g")
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
        applicant_telegram_id=100,
        applicant_username="alice",
        inviter_id=inv.id,
        status=APP_STATUS_APPROVED,
        wizard_step=0,
        reviewed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    session.add(app)
    await session.flush()
    return app


async def _add_rei(
    session,
    *,
    applicant_id: int,
    username: str | None,
    status: str,
    amount_cents: int,
    submitted_at: datetime,
    paid_at: datetime | None = None,
) -> ReimbursementRequest:
    app = await _seed_inviter_app(session)
    r = ReimbursementRequest(
        applicant_telegram_id=applicant_id,
        applicant_username=username,
        application_id=app.id,
        status=status,
        wizard_step=0,
        amount_cents=amount_cents,
        submitted_at=submitted_at,
        paid_at=paid_at,
    )
    session.add(r)
    await session.flush()
    return r


# ---------- 报表内容 ----------


@pytest.mark.asyncio
async def test_weekly_report_text_contains_core_fields(session):
    await reimbursement_settings.set_monthly_budget_cents(session, 100000)
    await reimbursement_settings.set_monthly_remaining_cents(session, 80000)

    text = await reports.generate_weekly_report_text(session)
    assert "📊 报销周报" in text
    assert "申请数" in text
    assert "总发放" in text
    assert "1000.00" in text  # 月预算
    assert "800.00" in text   # 当前剩余


@pytest.mark.asyncio
async def test_monthly_report_text_contains_core_fields(session):
    await reimbursement_settings.set_monthly_budget_cents(session, 50000)
    await reimbursement_settings.set_monthly_remaining_cents(session, 50000)

    text = await reports.generate_monthly_report_text(session)
    assert "📊 报销月报" in text
    assert "总发放" in text


@pytest.mark.asyncio
async def test_report_period_aggregates_correctly(session):
    """放几条在窗口内 + 几条在窗口外，验证只统计窗口内的。"""
    utc_start, utc_end, _, _ = reports.previous_week_range()
    # 在窗口内：1 paid 1 rejected
    inside_paid_at = utc_start + (utc_end - utc_start) / 2
    await _add_rei(
        session,
        applicant_id=100,
        username="alice",
        status=REI_STATUS_PAID,
        amount_cents=5000,
        submitted_at=inside_paid_at,
        paid_at=inside_paid_at,
    )
    await _add_rei(
        session,
        applicant_id=101,
        username="bob",
        status=REI_STATUS_REJECTED,
        amount_cents=5000,
        submitted_at=inside_paid_at,
    )
    # 窗口外：很久以前
    await _add_rei(
        session,
        applicant_id=102,
        username="carol",
        status=REI_STATUS_PAID,
        amount_cents=5000,
        submitted_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        paid_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    text = await reports.generate_weekly_report_text(session)
    # 应统计到 2 条申请（1 paid + 1 rejected），不应含 2025 那条
    assert "申请数：2" in text
    assert "alice" in text  # paid 用户进 Top
    assert "carol" not in text


# ---------- 月预算重置 ----------


@pytest.mark.asyncio
async def test_budget_reset_only_runs_on_reset_day(session, monkeypatch):
    await reimbursement_settings.set_monthly_budget_cents(session, 100000)
    await reimbursement_settings.set_monthly_remaining_cents(session, 30000)

    # 当前日不是 reset_day → 不重置
    from datetime import date as _date

    today = reports.now_local().date()
    other_day = today.day + 1 if today.day < 28 else 1
    await reimbursement_settings.set_reset_day(session, other_day)
    did = await reports.maybe_reset_monthly_budget(session)
    assert did is False
    assert (await reimbursement_settings.get_monthly_remaining_cents(session)) == 30000

    # 把 reset_day 设为今天 → 重置
    await reimbursement_settings.set_reset_day(session, today.day if today.day <= 28 else 28)
    did = await reports.maybe_reset_monthly_budget(session)
    assert did is True
    assert (await reimbursement_settings.get_monthly_remaining_cents(session)) == 100000


# ---------- weekday/monthday gates ----------


def test_period_ranges_are_monotonic():
    w_start, w_end, _, _ = reports.previous_week_range()
    m_start, m_end, _, _ = reports.previous_month_range()
    assert w_start < w_end
    assert m_start < m_end
    # 上周区间应该正好 7 天
    assert (w_end - w_start).days == 7


def test_should_run_weekly_and_monthly_helpers_return_bool():
    # 不依赖真实日期，只验证返回类型
    assert isinstance(reports.should_run_weekly_today(), bool)
    assert isinstance(reports.should_run_monthly_today(), bool)
