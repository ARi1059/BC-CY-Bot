"""
报销周报 / 月报 + 月预算自动重置（[REQ §8.5.8]）。

报表生成函数返回纯字符串，便于单测；JobQueue 在 bot 层负责调用 + 推送。
所有时间计算基于 `settings.TIMEZONE`（默认 Asia/Shanghai），转 UTC 查询。
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.config import settings
from bccy_bot.db.models.enums import (
    REI_STATUS_APPROVED,
    REI_STATUS_CANCELLED,
    REI_STATUS_PAID,
    REI_STATUS_PENDING,
    REI_STATUS_REJECTED,
)
from bccy_bot.db.models.reimbursement_request import ReimbursementRequest
from bccy_bot.repositories import reimbursement_settings

log = structlog.get_logger()


# ---------- 时区帮助 ----------


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone)
    except Exception:  # noqa: BLE001
        return ZoneInfo("Asia/Shanghai")


def now_local() -> datetime:
    return datetime.now(tz=_tz())


def _to_utc(dt_local: datetime) -> datetime:
    return dt_local.astimezone(timezone.utc)


def previous_week_range() -> tuple[datetime, datetime, date, date]:
    """
    返回 (utc_start, utc_end, local_start_date, local_end_date)。
    本地时间上周一 00:00 ~ 本周一 00:00（左闭右开）。
    """
    now = now_local()
    # 本地"今天 00:00"
    today_local_midnight = datetime.combine(now.date(), time(0, 0), tzinfo=_tz())
    # 距上周一：今天是周 X (Mon=0...Sun=6)，上周一是 today - (weekday + 7) 天
    days_to_last_monday = now.weekday() + 7
    last_monday = today_local_midnight - timedelta(days=days_to_last_monday)
    this_monday = last_monday + timedelta(days=7)
    return (
        _to_utc(last_monday),
        _to_utc(this_monday),
        last_monday.date(),
        this_monday.date() - timedelta(days=1),
    )


def previous_month_range() -> tuple[datetime, datetime, date, date]:
    """返回 (utc_start, utc_end, local_first_day, local_last_day)。"""
    now = now_local()
    first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 上月最后一天 = 本月 1 号 - 1 天
    last_prev = first_this - timedelta(days=1)
    first_prev = last_prev.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (
        _to_utc(first_prev),
        _to_utc(first_this),
        first_prev.date(),
        last_prev.date(),
    )


# ---------- 报表数据 ----------


@dataclass
class PeriodReport:
    period_label: str  # 周报/月报 时间区间字符串
    submitted_total: int
    by_status: dict[str, int]  # paid/approved/rejected/pending/cancelled
    paid_amount_cents: int
    monthly_budget_cents: int
    monthly_remaining_cents: int
    top_users: list[tuple[int, str | None, int]]  # (tg_id, username, count)
    anomalies: int = 0


async def _build_period_report(
    session: AsyncSession,
    *,
    utc_start: datetime,
    utc_end: datetime,
    period_label: str,
) -> PeriodReport:
    # 提交数（submitted_at 在区间内）
    submitted_total = (
        await session.execute(
            select(func.count(ReimbursementRequest.id)).where(
                ReimbursementRequest.submitted_at >= utc_start,
                ReimbursementRequest.submitted_at < utc_end,
            )
        )
    ).scalar_one()

    # 各状态分布（按 submitted_at 归属，保证一致性）
    rows = (
        await session.execute(
            select(ReimbursementRequest.status, func.count(ReimbursementRequest.id))
            .where(
                ReimbursementRequest.submitted_at >= utc_start,
                ReimbursementRequest.submitted_at < utc_end,
            )
            .group_by(ReimbursementRequest.status)
        )
    ).all()
    by_status = {r[0]: int(r[1]) for r in rows}

    # 已发放总额（paid，按 paid_at 归属）
    paid_amount = (
        await session.execute(
            select(func.coalesce(func.sum(ReimbursementRequest.amount_cents), 0)).where(
                ReimbursementRequest.status == REI_STATUS_PAID,
                ReimbursementRequest.paid_at >= utc_start,
                ReimbursementRequest.paid_at < utc_end,
            )
        )
    ).scalar_one()

    # 报销次数 Top（按 submitted_at 区间）
    user_rows = (
        await session.execute(
            select(
                ReimbursementRequest.applicant_telegram_id,
                ReimbursementRequest.applicant_username,
            )
            .where(
                ReimbursementRequest.submitted_at >= utc_start,
                ReimbursementRequest.submitted_at < utc_end,
                ReimbursementRequest.status.in_((REI_STATUS_APPROVED, REI_STATUS_PAID)),
            )
        )
    ).all()
    counter: Counter[int] = Counter()
    name_map: dict[int, str | None] = {}
    for tg_id, uname in user_rows:
        counter[tg_id] += 1
        # 保留最近一次的 username（可能为空）
        if uname is not None:
            name_map[tg_id] = uname
    top_users = [
        (tg_id, name_map.get(tg_id), cnt) for tg_id, cnt in counter.most_common(5)
    ]

    return PeriodReport(
        period_label=period_label,
        submitted_total=int(submitted_total),
        by_status=by_status,
        paid_amount_cents=int(paid_amount),
        monthly_budget_cents=await reimbursement_settings.get_monthly_budget_cents(session),
        monthly_remaining_cents=await reimbursement_settings.get_monthly_remaining_cents(session),
        top_users=top_users,
    )


def _format_report(report: PeriodReport, *, title: str) -> str:
    def yuan(cents: int) -> str:
        return reimbursement_settings.cents_to_yuan_display(cents)

    paid = report.by_status.get(REI_STATUS_PAID, 0)
    approved_no_pay = report.by_status.get(REI_STATUS_APPROVED, 0)
    rejected = report.by_status.get(REI_STATUS_REJECTED, 0)
    pending = report.by_status.get(REI_STATUS_PENDING, 0)
    cancelled = report.by_status.get(REI_STATUS_CANCELLED, 0)

    lines = [
        f"📊 {title} ({report.period_label})",
        "─────────────────────────",
        f"申请数：{report.submitted_total}",
        f"  已付款：{paid}",
        f"  已批准待付款：{approved_no_pay}",
        f"  已拒绝：{rejected}",
        f"  待审核：{pending}",
        f"  已取消：{cancelled}",
        f"总发放：{yuan(report.paid_amount_cents)} 元",
        f"本月预算：{yuan(report.monthly_budget_cents)} 元（当前剩余 {yuan(report.monthly_remaining_cents)}）",
    ]
    if report.top_users:
        lines.append("")
        lines.append("📌 报销次数 Top")
        for tg_id, uname, cnt in report.top_users:
            name = f"@{uname}" if uname else f"#{tg_id}"
            lines.append(f"  {name}：{cnt} 次")
    return "\n".join(lines)


async def generate_weekly_report_text(session: AsyncSession) -> str:
    utc_start, utc_end, local_start, local_end = previous_week_range()
    label = f"{local_start.isoformat()} ~ {local_end.isoformat()}"
    report = await _build_period_report(
        session, utc_start=utc_start, utc_end=utc_end, period_label=label
    )
    return _format_report(report, title="报销周报")


async def generate_monthly_report_text(session: AsyncSession) -> str:
    utc_start, utc_end, local_start, local_end = previous_month_range()
    label = f"{local_start.isoformat()} ~ {local_end.isoformat()}"
    report = await _build_period_report(
        session, utc_start=utc_start, utc_end=utc_end, period_label=label
    )
    return _format_report(report, title="报销月报")


# ---------- 月预算自动重置 ----------


async def maybe_reset_monthly_budget(session: AsyncSession) -> bool:
    """
    JobQueue 每天 00:00 调用：若当日是 reset_day 则把 monthly_remaining 重置为 monthly_budget。
    返回是否执行了重置。
    """
    reset_day = await reimbursement_settings.get_reset_day(session)
    today_local = now_local().date()
    if today_local.day != reset_day:
        return False
    budget = await reimbursement_settings.get_monthly_budget_cents(session)
    await reimbursement_settings.set_monthly_remaining_cents(session, budget)
    log.info("reimbursement_budget_reset", to_cents=budget, day=today_local.isoformat())
    return True


def should_run_weekly_today() -> bool:
    """本地"今天"是周一就跑周报。"""
    return now_local().weekday() == 0


def should_run_monthly_today() -> bool:
    """本地"今天"是 1 号就跑月报。"""
    return now_local().day == 1
