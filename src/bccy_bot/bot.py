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
    reimbursement as adm_rei,
    reimbursement_audit as adm_rev,
    settings_ui as adm_settings,
    stats as adm_stats,
    stubs as adm_stubs,
    teachers as adm_teachers,
)
from bccy_bot.handlers.common import chat_member as chat_member_handler
from bccy_bot.handlers.inviter import audit as inviter_audit
from bccy_bot.handlers.inviter import panel as inviter_panel
from bccy_bot.handlers.user import recovery as user_recovery
from bccy_bot.handlers.user import reimburse as user_reimburse
from bccy_bot.handlers.user import wizard as wizard_handlers
from bccy_bot.handlers.user.start import start_command
from bccy_bot.keyboards.inviter_callbacks import (
    INV_PANEL_BACK,
    INV_PANEL_PENDING,
    INV_PANEL_REPOST_PREFIX,
    INV_PANEL_STATS,
)
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
    ADM_TEA_ADD,
    ADM_TEA_ADD_CANCEL,
    ADM_TEA_ADD_CONFIRM,
    ADM_TEA_ADD_PICK_TIER_PREFIX,
    ADM_TEA_LIST,
    ADM_TEA_LIST_PREFIX,
    ADM_TEA_REMOVE_CONFIRM_PREFIX,
    ADM_TEA_REMOVE_PREFIX,
    ADM_TEA_SET_GROUP_OPEN_PREFIX,
    ADM_TEA_SET_TIER_OPEN_PREFIX,
    ADM_TEA_SET_TIER_VALUE_PREFIX,
    ADM_TEA_TOGGLE_PREFIX,
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
    ADM_REI,
    ADM_REI_ELIG,
    ADM_REI_ELIG_ADD,
    ADM_REI_ELIG_REMOVE_CONFIRM_PREFIX,
    ADM_REI_ELIG_REMOVE_PREFIX,
    ADM_REI_APPROVED_LIST,
    ADM_REI_HISTORY_LIST,
    ADM_REI_OVERRIDE_ADD,
    ADM_REI_OVERRIDE_REMOVE_CONFIRM_PREFIX,
    ADM_REI_OVERRIDE_REMOVE_PREFIX,
    ADM_REI_OVERRIDES,
    ADM_REI_PENDING_LIST,
    ADM_REI_RESEND_AUDIT_PREFIX,
    ADM_REI_RESEND_PAYMENT_PREFIX,
    ADM_REI_RESET_REMAINING,
    ADM_REI_SET_BUDGET,
    ADM_REI_SET_COOLDOWN,
    ADM_REI_SET_RESET_DAY,
    ADM_REI_SETTINGS,
    ADM_REI_TOGGLE,
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
    USER_START_REIMBURSE,
    USER_USE_RECOVERY_KEY,
    USER_VIEW_STATUS,
)
from bccy_bot.keyboards.reimburse_callbacks import (
    REI_USER_BACK,
    REI_USER_CANCEL,
    REI_USER_CONFIRM_CANCEL,
    REI_USER_DISMISS,
    REI_USER_PICK_TEACHER_PAGE_PREFIX,
    REI_USER_PICK_TEACHER_PREFIX,
    REI_USER_PREVIEW_CONFIRM,
    REI_USER_PREVIEW_REDO,
)
from bccy_bot.keyboards.reimburse_audit_callbacks import (
    REV_APPROVE_PREFIX,
    REV_REJECT_PREFIX,
    REV_REJECT_REASON_PREFIX,
    REV_REJECT_SKIP_PREFIX,
    REV_VIEW_PREFIX,
)
from bccy_bot.repositories import admin_repo as admin_repo_pkg
from bccy_bot.repositories.admin_repo import ensure_initial_super_admin
from bccy_bot.services import link_tracking_service
from bccy_bot.services import reimbursement_reports_service as rei_reports
from bccy_bot.utils.retry import telegram_retry
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

        # 报销系统：每天 00:00 检查是否需要重置月预算
        from datetime import time as _time

        application.job_queue.run_daily(
            _reimbursement_budget_reset_job,
            time=_time(0, 0, 5),
            name="reimbursement_budget_reset",
        )
        # 周报：每天 00:05 跑一次，job 内部判断是否为周一
        application.job_queue.run_daily(
            _reimbursement_weekly_report_job,
            time=_time(0, 5, 0),
            name="reimbursement_weekly_report",
        )
        # 月报：每天 00:10 跑一次，job 内部判断是否为 1 号
        application.job_queue.run_daily(
            _reimbursement_monthly_report_job,
            time=_time(0, 10, 0),
            name="reimbursement_monthly_report",
        )
        log.info("reimbursement_jobs_scheduled")


async def _sweep_expired_links_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """JobQueue 回调：扫描标记过期链接 + 推送日志频道。"""
    factory = get_session_factory(context)
    async with factory() as session:
        try:
            expired = await link_tracking_service.sweep_expired(session, bot=context.bot)
            await session.commit()
            if expired:
                log.info("expired_link_sweep_done", marked=len(expired))
        except Exception:  # noqa: BLE001
            await session.rollback()
            log.exception("expired_link_sweep_failed")


@telegram_retry(max_attempts=3)
async def _dm(bot, chat_id: int, text: str) -> None:
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=True)


async def _reimbursement_budget_reset_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """每天 00:00 跑：若当日是 reset_day 则把 monthly_remaining 重置回 monthly_budget。"""
    factory = get_session_factory(context)
    async with factory() as session:
        try:
            did_reset = await rei_reports.maybe_reset_monthly_budget(session)
            await session.commit()
            if did_reset:
                log.info("reimbursement_budget_reset_done")
        except Exception:  # noqa: BLE001
            await session.rollback()
            log.exception("reimbursement_budget_reset_failed")


async def _reimbursement_weekly_report_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """周一 00:05 跑：生成上周周报并私聊所有超级管理员。"""
    if not rei_reports.should_run_weekly_today():
        return
    factory = get_session_factory(context)
    async with factory() as session:
        try:
            text = await rei_reports.generate_weekly_report_text(session)
            supers = [
                a for a in await admin_repo_pkg.list_all(session) if a.role == "super"
            ]
        except Exception:  # noqa: BLE001
            log.exception("reimbursement_weekly_report_build_failed")
            return

    for adm in supers:
        try:
            await _dm(context.bot, adm.telegram_user_id, text)
        except Exception:  # noqa: BLE001
            log.exception(
                "reimbursement_weekly_report_send_failed",
                admin_telegram_id=adm.telegram_user_id,
            )
    log.info("reimbursement_weekly_report_done", recipients=len(supers))


async def _reimbursement_monthly_report_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """每月 1 号 00:10 跑：生成上月月报并私聊所有超级管理员。"""
    if not rei_reports.should_run_monthly_today():
        return
    factory = get_session_factory(context)
    async with factory() as session:
        try:
            text = await rei_reports.generate_monthly_report_text(session)
            supers = [
                a for a in await admin_repo_pkg.list_all(session) if a.role == "super"
            ]
        except Exception:  # noqa: BLE001
            log.exception("reimbursement_monthly_report_build_failed")
            return

    for adm in supers:
        try:
            await _dm(context.bot, adm.telegram_user_id, text)
        except Exception:  # noqa: BLE001
            log.exception(
                "reimbursement_monthly_report_send_failed",
                admin_telegram_id=adm.telegram_user_id,
            )
    log.info("reimbursement_monthly_report_done", recipients=len(supers))


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
    application.add_handler(CommandHandler("panel", inviter_panel.panel_command))
    application.add_handler(CommandHandler("reimburse", user_reimburse.reimburse_command))

    # === Welcome card callbacks ===
    application.add_handler(CallbackQueryHandler(wizard_handlers.on_start_apply, pattern=f"^{USER_START_APPLY}$"))
    application.add_handler(CallbackQueryHandler(wizard_handlers.on_help, pattern=f"^{USER_HELP}$"))
    application.add_handler(
        CallbackQueryHandler(user_recovery.on_use_recovery_key, pattern=f"^{USER_USE_RECOVERY_KEY}$")
    )
    application.add_handler(
        CallbackQueryHandler(user_reimburse.on_start_from_welcome, pattern=f"^{USER_START_REIMBURSE}$")
    )

    # === Reimbursement user wizard callbacks ===
    application.add_handler(
        CallbackQueryHandler(user_reimburse.on_back, pattern=f"^{REI_USER_BACK}$")
    )
    application.add_handler(
        CallbackQueryHandler(user_reimburse.on_cancel, pattern=f"^{REI_USER_CANCEL}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            user_reimburse.on_confirm_cancel, pattern=f"^{REI_USER_CONFIRM_CANCEL}$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(user_reimburse.on_dismiss, pattern=f"^{REI_USER_DISMISS}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            user_reimburse.on_preview_confirm, pattern=f"^{REI_USER_PREVIEW_CONFIRM}$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(user_reimburse.on_preview_redo, pattern=f"^{REI_USER_PREVIEW_REDO}$")
    )
    # v1.0.0-beta.3 选老师
    application.add_handler(
        CallbackQueryHandler(
            user_reimburse.on_pick_teacher, pattern=f"^{REI_USER_PICK_TEACHER_PREFIX}\\d+$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            user_reimburse.on_pick_teacher_page, pattern=f"^{REI_USER_PICK_TEACHER_PAGE_PREFIX}\\d+$"
        )
    )

    # === Reimbursement admin review callbacks ===
    application.add_handler(
        CallbackQueryHandler(adm_rev.on_approve, pattern=f"^{REV_APPROVE_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rev.on_reject, pattern=f"^{REV_REJECT_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rev.on_reject_reason, pattern=f"^{REV_REJECT_REASON_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rev.on_reject_skip, pattern=f"^{REV_REJECT_SKIP_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rev.on_view, pattern=f"^{REV_VIEW_PREFIX}\\d+$")
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

    # === Admin: reimburse teachers (v1.0.0-beta.3) ===
    application.add_handler(
        CallbackQueryHandler(
            adm_teachers.on_list, pattern=f"^({ADM_TEA_LIST}|{ADM_TEA_LIST_PREFIX}\\d+)$"
        )
    )
    application.add_handler(CallbackQueryHandler(adm_teachers.on_add, pattern=f"^{ADM_TEA_ADD}$"))
    application.add_handler(
        CallbackQueryHandler(
            adm_teachers.on_add_pick_tier, pattern=f"^{ADM_TEA_ADD_PICK_TIER_PREFIX}\\d+$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(adm_teachers.on_add_confirm, pattern=f"^{ADM_TEA_ADD_CONFIRM}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_teachers.on_add_cancel, pattern=f"^{ADM_TEA_ADD_CANCEL}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_teachers.on_toggle, pattern=f"^{ADM_TEA_TOGGLE_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_teachers.on_remove, pattern=f"^{ADM_TEA_REMOVE_PREFIX}\\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_teachers.on_remove_confirm, pattern=f"^{ADM_TEA_REMOVE_CONFIRM_PREFIX}\\d+$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_teachers.on_set_tier_open, pattern=f"^{ADM_TEA_SET_TIER_OPEN_PREFIX}\\d+$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_teachers.on_set_tier_value,
            pattern=f"^{ADM_TEA_SET_TIER_VALUE_PREFIX}\\d+:\\d+$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_teachers.on_set_group_open, pattern=f"^{ADM_TEA_SET_GROUP_OPEN_PREFIX}\\d+$"
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

    # === Admin: reimbursement panel ===
    application.add_handler(CallbackQueryHandler(adm_rei.on_panel, pattern=f"^{ADM_REI}$"))
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_settings_panel, pattern=f"^{ADM_REI_SETTINGS}$")
    )
    application.add_handler(CallbackQueryHandler(adm_rei.on_toggle, pattern=f"^{ADM_REI_TOGGLE}$"))
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_set_budget, pattern=f"^{ADM_REI_SET_BUDGET}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_reset_remaining, pattern=f"^{ADM_REI_RESET_REMAINING}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_set_cooldown, pattern=f"^{ADM_REI_SET_COOLDOWN}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_set_reset_day, pattern=f"^{ADM_REI_SET_RESET_DAY}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_eligibility_panel, pattern=f"^{ADM_REI_ELIG}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_eligibility_add, pattern=f"^{ADM_REI_ELIG_ADD}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_rei.on_eligibility_remove, pattern=f"^{ADM_REI_ELIG_REMOVE_PREFIX}\\d+$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_rei.on_eligibility_remove_confirm,
            pattern=f"^{ADM_REI_ELIG_REMOVE_CONFIRM_PREFIX}\\d+$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_overrides_panel, pattern=f"^{ADM_REI_OVERRIDES}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_override_add, pattern=f"^{ADM_REI_OVERRIDE_ADD}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_rei.on_override_remove, pattern=f"^{ADM_REI_OVERRIDE_REMOVE_PREFIX}\\d+$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_rei.on_override_remove_confirm,
            pattern=f"^{ADM_REI_OVERRIDE_REMOVE_CONFIRM_PREFIX}\\d+$",
        )
    )
    # M14: 待审核 / 待付款 / 历史 / 行内动作
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_pending_list, pattern=f"^{ADM_REI_PENDING_LIST}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_approved_list, pattern=f"^{ADM_REI_APPROVED_LIST}$")
    )
    application.add_handler(
        CallbackQueryHandler(adm_rei.on_history_list, pattern=f"^{ADM_REI_HISTORY_LIST}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_rei.on_resend_audit, pattern=f"^{ADM_REI_RESEND_AUDIT_PREFIX}\\d+$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            adm_rei.on_resend_payment, pattern=f"^{ADM_REI_RESEND_PAYMENT_PREFIX}\\d+$"
        )
    )

    # === Inviter /panel callbacks ===
    application.add_handler(CallbackQueryHandler(inviter_panel.on_back, pattern=f"^{INV_PANEL_BACK}$"))
    application.add_handler(
        CallbackQueryHandler(inviter_panel.on_pending_list, pattern=f"^{INV_PANEL_PENDING}$")
    )
    application.add_handler(
        CallbackQueryHandler(inviter_panel.on_my_stats, pattern=f"^{INV_PANEL_STATS}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            inviter_panel.on_repost_materials, pattern=f"^{INV_PANEL_REPOST_PREFIX}\\d+$"
        )
    )

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
