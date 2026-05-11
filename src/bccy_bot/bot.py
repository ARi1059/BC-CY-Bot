import structlog
from telegram.ext import Application, CommandHandler

from bccy_bot.config import settings
from bccy_bot.db.session import make_engine, make_session_factory
from bccy_bot.handlers.user.start import start_command
from bccy_bot.repositories.admin_repo import ensure_initial_super_admin

log = structlog.get_logger()


async def _post_init(application: Application) -> None:
    """启动时注入：初始超级管理员 + 数据库 session factory。"""
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    async with session_factory() as session:
        result = await ensure_initial_super_admin(session, settings.initial_super_admin_id)
        await session.commit()

    log.info("super_admin_ensured", **result)

    application.bot_data["engine"] = engine
    application.bot_data["session_factory"] = session_factory


async def _post_shutdown(application: Application) -> None:
    engine = application.bot_data.get("engine")
    if engine is not None:
        await engine.dispose()
        log.info("engine_disposed")


def build_application() -> Application:
    application = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start_command))
    return application
