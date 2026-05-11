import structlog
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bccy_bot.config import settings
from bccy_bot.db.session import make_engine, make_session_factory
from bccy_bot.handlers.user import wizard as wizard_handlers
from bccy_bot.handlers.user.start import start_command
from bccy_bot.keyboards.callback_data import (
    USER_BACK,
    USER_CANCEL,
    USER_CANCEL_AND_RESTART,
    USER_CONFIRM_CANCEL,
    USER_DISMISS,
    USER_HELP,
    USER_INVITERS_PAGE_PREFIX,
    USER_PICK_INVITER_PREFIX,
    USER_PREVIEW_CONFIRM,
    USER_PREVIEW_REDO,
    USER_START_APPLY,
    USER_USE_RECOVERY_KEY,
    USER_VIEW_STATUS,
)
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

    # === Commands ===
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", wizard_handlers.on_help))

    # === Welcome card callbacks ===
    application.add_handler(CallbackQueryHandler(wizard_handlers.on_start_apply, pattern=f"^{USER_START_APPLY}$"))
    application.add_handler(CallbackQueryHandler(wizard_handlers.on_help, pattern=f"^{USER_HELP}$"))
    application.add_handler(
        CallbackQueryHandler(wizard_handlers.on_use_recovery_key_placeholder, pattern=f"^{USER_USE_RECOVERY_KEY}$")
    )

    # === Existing-pending card ===
    application.add_handler(CallbackQueryHandler(wizard_handlers.on_view_status, pattern=f"^{USER_VIEW_STATUS}$"))
    application.add_handler(
        CallbackQueryHandler(wizard_handlers.on_cancel_and_restart, pattern=f"^{USER_CANCEL_AND_RESTART}$")
    )

    # === Wizard navigation ===
    application.add_handler(
        CallbackQueryHandler(wizard_handlers.on_pick_inviter, pattern=f"^{USER_PICK_INVITER_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(wizard_handlers.on_inviters_page, pattern=f"^{USER_INVITERS_PAGE_PREFIX}\\d+$")
    )
    application.add_handler(CallbackQueryHandler(wizard_handlers.on_back, pattern=f"^{USER_BACK}$"))
    application.add_handler(CallbackQueryHandler(wizard_handlers.on_cancel, pattern=f"^{USER_CANCEL}$"))
    application.add_handler(
        CallbackQueryHandler(wizard_handlers.on_confirm_cancel, pattern=f"^{USER_CONFIRM_CANCEL}$")
    )
    application.add_handler(CallbackQueryHandler(wizard_handlers.on_dismiss, pattern=f"^{USER_DISMISS}$"))

    # === Preview ===
    application.add_handler(
        CallbackQueryHandler(wizard_handlers.on_preview_confirm, pattern=f"^{USER_PREVIEW_CONFIRM}$")
    )
    application.add_handler(
        CallbackQueryHandler(wizard_handlers.on_preview_redo, pattern=f"^{USER_PREVIEW_REDO}$")
    )

    # === Material messages (photo / text in private chat) ===
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (filters.PHOTO | (filters.TEXT & ~filters.COMMAND)),
            wizard_handlers.on_material_message,
        )
    )

    return application
