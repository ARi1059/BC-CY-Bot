import structlog

from bccy_bot.bot import ALLOWED_UPDATES, build_application
from bccy_bot.config import settings
from bccy_bot.utils.logging_setup import configure_logging

log = structlog.get_logger()


def main() -> None:
    configure_logging(settings.log_level)
    log.info(
        "bot_starting",
        db_backend=settings.database_url.split("://", 1)[0],
        initial_super_admin=settings.initial_super_admin_id,
        log_level=settings.log_level,
    )
    application = build_application()
    log.info("bot_polling", allowed_updates=ALLOWED_UPDATES)
    application.run_polling(allowed_updates=ALLOWED_UPDATES)


if __name__ == "__main__":
    main()
