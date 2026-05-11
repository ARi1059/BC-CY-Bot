"""从 PTB ContextTypes 取出 async session factory。"""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram.ext import ContextTypes


def get_session_factory(context: ContextTypes.DEFAULT_TYPE) -> async_sessionmaker[AsyncSession]:
    factory = context.application.bot_data.get("session_factory")
    if factory is None:
        raise RuntimeError("session_factory not initialized in bot_data; check post_init wiring")
    return factory


@asynccontextmanager
async def session_scope(context: ContextTypes.DEFAULT_TYPE):
    """语法糖：一个 with 块内拿到 session 并自动 commit / rollback。"""
    factory = get_session_factory(context)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
