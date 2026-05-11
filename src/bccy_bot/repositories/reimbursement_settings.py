"""报销系统设置项的便捷读写（基于通用 settings 表）。"""

from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.enums import (
    SK_REI_BUDGET_RESET_DAY,
    SK_REI_DEFAULT_COOLDOWN_DAYS,
    SK_REI_FIXED_AMOUNT_CENTS,
    SK_REI_GLOBAL_ENABLED,
    SK_REI_MONTHLY_BUDGET_CENTS,
    SK_REI_MONTHLY_REMAINING_CENTS,
)
from bccy_bot.repositories import settings_repo


# Clamp 范围
MIN_RESET_DAY = 1
MAX_RESET_DAY = 28
MIN_COOLDOWN_DAYS = 1
MAX_COOLDOWN_DAYS = 90


async def is_enabled(session: AsyncSession) -> bool:
    v = await settings_repo.get(session, SK_REI_GLOBAL_ENABLED)
    return (v or "").strip().lower() == "true"


async def set_enabled(session: AsyncSession, value: bool) -> None:
    await settings_repo.set_value(session, SK_REI_GLOBAL_ENABLED, "true" if value else "false")


async def get_fixed_amount_cents(session: AsyncSession) -> int:
    return await settings_repo.get_int(session, SK_REI_FIXED_AMOUNT_CENTS, 0)


async def set_fixed_amount_cents(session: AsyncSession, cents: int) -> None:
    cents = max(0, int(cents))
    await settings_repo.set_value(session, SK_REI_FIXED_AMOUNT_CENTS, str(cents))


async def get_monthly_budget_cents(session: AsyncSession) -> int:
    return await settings_repo.get_int(session, SK_REI_MONTHLY_BUDGET_CENTS, 0)


async def set_monthly_budget_cents(session: AsyncSession, cents: int) -> None:
    cents = max(0, int(cents))
    await settings_repo.set_value(session, SK_REI_MONTHLY_BUDGET_CENTS, str(cents))


async def get_monthly_remaining_cents(session: AsyncSession) -> int:
    return await settings_repo.get_int(session, SK_REI_MONTHLY_REMAINING_CENTS, 0)


async def set_monthly_remaining_cents(session: AsyncSession, cents: int) -> None:
    cents = max(0, int(cents))
    await settings_repo.set_value(session, SK_REI_MONTHLY_REMAINING_CENTS, str(cents))


async def get_reset_day(session: AsyncSession) -> int:
    d = await settings_repo.get_int(session, SK_REI_BUDGET_RESET_DAY, 1)
    return max(MIN_RESET_DAY, min(MAX_RESET_DAY, d))


async def set_reset_day(session: AsyncSession, day: int) -> None:
    day = max(MIN_RESET_DAY, min(MAX_RESET_DAY, int(day)))
    await settings_repo.set_value(session, SK_REI_BUDGET_RESET_DAY, str(day))


async def get_default_cooldown_days(session: AsyncSession) -> int:
    d = await settings_repo.get_int(session, SK_REI_DEFAULT_COOLDOWN_DAYS, 7)
    return max(MIN_COOLDOWN_DAYS, min(MAX_COOLDOWN_DAYS, d))


async def set_default_cooldown_days(session: AsyncSession, days: int) -> None:
    days = max(MIN_COOLDOWN_DAYS, min(MAX_COOLDOWN_DAYS, int(days)))
    await settings_repo.set_value(session, SK_REI_DEFAULT_COOLDOWN_DAYS, str(days))


# 用于面板展示
def cents_to_yuan_display(cents: int) -> str:
    return f"{cents / 100:.2f}"


def yuan_text_to_cents(text: str) -> int:
    """解析用户输入的金额文本 → 分。支持 '50' / '50.00' / '50.5'。失败抛 ValueError。"""
    text = text.strip().replace(",", "")
    if not text:
        raise ValueError("空字符串")
    yuan = float(text)
    if yuan < 0:
        raise ValueError("金额不能为负")
    return int(round(yuan * 100))
