import structlog
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bccy_bot.config import settings
from bccy_bot.db.session import make_engine, make_session_factory
from bccy_bot.handlers.admin import (
    admin_mgmt as adm_mgmt,
    blacklist as adm_blacklist,
    channels as adm_channels,
    groups as adm_groups,
    inviters as adm_inviters,
    panel as adm_panel,
    settings_ui as adm_settings,
    stats as adm_stats,
    stubs as adm_stubs,
)
from bccy_bot.handlers.common import chat_member as chat_member_handler
from bccy_bot.handlers.inviter import audit as inviter_audit
from bccy_bot.handlers.user import wizard as wizard_handlers
from bccy_bot.handlers.user.start import start_command
from bccy_bot.keyboards.admin_callbacks import (
    ADM_BACK,
    ADM_BL_ADD,
    ADM_BL_LIST,
    ADM_BL_LIST_PREFIX,
    ADM_BL_REMOVE_CONFIRM_PREFIX,
    ADM_BL_REMOVE_PREFIX,
    ADM_CONFIG,
    ADM_CONFIG_EDIT_TTL,
    ADM_DISMISS,
    ADM_GRP_ADD,
    ADM_GRP_LIST,
    ADM_GRP_LIST_PREFIX,
    ADM_GRP_REMOVE_CONFIRM_PREFIX,
    ADM_GRP_REMOVE_PREFIX,
    ADM_INV_ADD,
    ADM_INV_ADD_CANCEL,
    ADM_INV_ADD_CONFIRM,
    ADM_INV_ADD_PICK_GRP_PREFIX,
    ADM_INV_ADD_SET_MODE_PREFIX,
    ADM_INV_ADD_TOGGLE_MAT_PREFIX,
    ADM_INV_LIST,
    ADM_INV_LIST_PREFIX,
    ADM_INV_REMOVE_CONFIRM_PREFIX,
    ADM_INV_REMOVE_PREFIX,
    ADM_INV_TOGGLE_PREFIX,
    ADM_KEYS,
    ADM_LOG_CHANNEL,
    ADM_LOG_CHANNEL_BIND,
    ADM_LOG_CHANNEL_UNBIND,
    ADM_MGMT_ADD,
    ADM_MGMT_LIST,
    ADM_MGMT_REMOVE_CONFIRM_PREFIX,
    ADM_MGMT_REMOVE_PREFIX,
    ADM_MGMT_TRANSFER_CONFIRM_PREFIX,
    ADM_MGMT_TRANSFER_PREFIX,
    ADM_PENDING,
    ADM_REPORT_CHANNEL,
    ADM_REPORT_CHANNEL_BIND,
    ADM_REPORT_CHANNEL_UNBIND,
    ADM_STATS,
)
from bccy_bot.keyboards.callback_data import (
    INVITER_APPROVE_PREFIX,
    INVITER_REJECT_PREFIX,
    INVITER_REJECT_REASON_PREFIX,
    INVITER_REJECT_SKIP_PREFIX,
    INVITER_VIEW_MATERIALS_PREFIX,
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
from bccy_bot.services import link_tracking_service
from bccy_bot.utils.session import get_session_factory

log = structlog.get_logger()


async def _post_init(application: Application) -> None:
    """启动时注入：初始超级管理员 + 数据库 session factory + 定时任务。"""
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    async with session_factory() as session:
        result = await ensure_initial_super_admin(session, settings.initial_super_admin_id)
        await session.commit()

    log.info("super_admin_ensured", **result)

    application.bot_data["engine"] = engine
    application.bot_data["session_factory"] = session_factory

    # 注册定时任务：每小时扫描过期未用链接
    if application.job_queue is not None:
        application.job_queue.run_repeating(
            _sweep_expired_links_job,
            interval=3600,
            first=300,  # 启动后 5 分钟首跑，留出时间让其他初始化完成
            name="expired_link_sweep",
        )
        log.info("expired_link_sweep_scheduled", interval_sec=3600)


async def _sweep_expired_links_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue 回调：扫描标记过期链接。"""
    factory = get_session_factory(context)
    async with factory() as session:
        try:
            expired = await link_tracking_service.sweep_expired(session)
            await session.commit()
            if expired:
                log.info("expired_link_sweep_done", marked=len(expired))
        except Exception:  # noqa: BLE001
            await session.rollback()
            log.exception("expired_link_sweep_failed")


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
    application.add_handler(CommandHandler("admin", adm_panel.admin_command))

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

    # === Inviter audit callbacks ===
    application.add_handler(
        CallbackQueryHandler(inviter_audit.on_approve, pattern=f"^{INVITER_APPROVE_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(inviter_audit.on_reject, pattern=f"^{INVITER_REJECT_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(inviter_audit.on_reject_reason, pattern=f"^{INVITER_REJECT_REASON_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(inviter_audit.on_reject_skip, pattern=f"^{INVITER_REJECT_SKIP_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(inviter_audit.on_view_materials, pattern=f"^{INVITER_VIEW_MATERIALS_PREFIX}\\d+$")
    )

    # === Material messages (photo / text in private chat) ===
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (filters.PHOTO | (filters.TEXT & ~filters.COMMAND)),
            wizard_handlers.on_material_message,
        )
    )

    # === Admin: 主面板 & 返回 ===
    application.add_handler(CallbackQueryHandler(adm_panel.on_back_to_panel, pattern=f"^{ADM_BACK}$"))
    application.add_handler(CallbackQueryHandler(adm_panel.on_dismiss, pattern=f"^{ADM_DISMISS}$"))

    # === Admin: groups ===
    application.add_handler(
        CallbackQueryHandler(adm_groups.on_list, pattern=f"^({ADM_GRP_LIST}|{ADM_GRP_LIST_PREFIX}\\d+)$")
    )
    application.add_handler(CallbackQueryHandler(adm_groups.on_add, pattern=f"^{ADM_GRP_ADD}$"))
    application.add_handler(
        CallbackQueryHandler(adm_groups.on_remove, pattern=f"^{ADM_GRP_REMOVE_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_groups.on_remove_confirm, pattern=f"^{ADM_GRP_REMOVE_CONFIRM_PREFIX}\\d+$"
        )
    )

    # === Admin: inviters ===
    application.add_handler(
        CallbackQueryHandler(adm_inviters.on_list, pattern=f"^({ADM_INV_LIST}|{ADM_INV_LIST_PREFIX}\\d+)$")
    )
    application.add_handler(CallbackQueryHandler(adm_inviters.on_add, pattern=f"^{ADM_INV_ADD}$"))
    application.add_handler(
        CallbackQueryHandler(adm_inviters.on_add_pick_group, pattern=f"^{ADM_INV_ADD_PICK_GRP_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_inviters.on_add_toggle_material, pattern=f"^{ADM_INV_ADD_TOGGLE_MAT_PREFIX}.+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_inviters.on_add_set_mode, pattern=f"^{ADM_INV_ADD_SET_MODE_PREFIX}.+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_inviters.on_add_confirm, pattern=f"^{ADM_INV_ADD_CONFIRM}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_inviters.on_add_cancel, pattern=f"^{ADM_INV_ADD_CANCEL}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_inviters.on_toggle, pattern=f"^{ADM_INV_TOGGLE_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_inviters.on_remove, pattern=f"^{ADM_INV_REMOVE_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_inviters.on_remove_confirm, pattern=f"^{ADM_INV_REMOVE_CONFIRM_PREFIX}\\d+$"
        )
    )

    # === Admin: blacklist ===
    application.add_handler(
        CallbackQueryHandler(
            adm_blacklist.on_list, pattern=f"^({ADM_BL_LIST}|{ADM_BL_LIST_PREFIX}\\d+)$"
        )
    )
    application.add_handler(CallbackQueryHandler(adm_blacklist.on_add, pattern=f"^{ADM_BL_ADD}$"))
    application.add_handler(
        CallbackQueryHandler(adm_blacklist.on_remove, pattern=f"^{ADM_BL_REMOVE_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_blacklist.on_remove_confirm, pattern=f"^{ADM_BL_REMOVE_CONFIRM_PREFIX}\\d+$"
        )
    )

    # === Admin: admins management ===
    application.add_handler(CallbackQueryHandler(adm_mgmt.on_list, pattern=f"^{ADM_MGMT_LIST}$"))
    application.add_handler(CallbackQueryHandler(adm_mgmt.on_add, pattern=f"^{ADM_MGMT_ADD}$"))
    application.add_handler(
        CallbackQueryHandler(adm_mgmt.on_remove, pattern=f"^{ADM_MGMT_REMOVE_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_mgmt.on_remove_confirm, pattern=f"^{ADM_MGMT_REMOVE_CONFIRM_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_mgmt.on_transfer, pattern=f"^{ADM_MGMT_TRANSFER_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_mgmt.on_transfer_confirm, pattern=f"^{ADM_MGMT_TRANSFER_CONFIRM_PREFIX}\\d+$"
        )
    )

    # === Admin: channels ===
    application.add_handler(CallbackQueryHandler(adm_channels.on_log_panel, pattern=f"^{ADM_LOG_CHANNEL}$"))
    application.add_handler(
        CallbackQueryHandler(adm_channels.on_log_bind, pattern=f"^{ADM_LOG_CHANNEL_BIND}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_channels.on_log_unbind, pattern=f"^{ADM_LOG_CHANNEL_UNBIND}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_channels.on_report_panel, pattern=f"^{ADM_REPORT_CHANNEL}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_channels.on_report_bind, pattern=f"^{ADM_REPORT_CHANNEL_BIND}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_channels.on_report_unbind, pattern=f"^{ADM_REPORT_CHANNEL_UNBIND}$")
    )

    # === Admin: system config ===
    application.add_handler(CallbackQueryHandler(adm_settings.on_panel, pattern=f"^{ADM_CONFIG}$"))
    application.add_handler(
        CallbackQueryHandler(adm_settings.on_edit_ttl, pattern=f"^{ADM_CONFIG_EDIT_TTL}$")
    )

    # === Admin: stats / stubs ===
    application.add_handler(CallbackQueryHandler(adm_stats.on_stats, pattern=f"^{ADM_STATS}$"))
    application.add_handler(CallbackQueryHandler(adm_stubs.on_pending, pattern=f"^{ADM_PENDING}$"))
    application.add_handler(CallbackQueryHandler(adm_stubs.on_keys, pattern=f"^{ADM_KEYS}$"))

    # === chat_member 更新（监听入群事件） ===
    application.add_handler(
        ChatMemberHandler(
            chat_member_handler.on_chat_member_update,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    return application


# 显式声明 polling 需要订阅的 update 类型；不订阅 chat_member 则 Telegram 不会推送
ALLOWED_UPDATES = [
    Update.MESSAGE,
    Update.CALLBACK_QUERY,
    Update.CHAT_MEMBER,
    Update.MY_CHAT_MEMBER,
]
