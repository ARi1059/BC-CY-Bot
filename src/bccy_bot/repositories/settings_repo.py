from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.settings import Setting


async def get(session: AsyncSession, key: str) -> str | None:
    s = await session.get(Setting, key)
    return s.value if s is not None else None


async def get_int(session: AsyncSession, key: str, default: int) -> int:
    v = await get(session, key)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


async def set_value(session: AsyncSession, key: str, value: str) -> None:
    s = await session.get(Setting, key)
    if s is None:
        s = Setting(key=key, value=value)
        session.add(s)
    else:
        s.value = value
    await session.flush()
