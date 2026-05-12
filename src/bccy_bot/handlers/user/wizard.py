"""申请人 wizard 的所有 callback / message handler。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.enums import APP_STATUS_PENDING, APP_STATUS_WIZARD, CT_PHOTO, CT_TEXT
from bccy_bot.handlers.user.render import (
    render_cancel_confirm,
    render_existing_pending,
    render_existing_wizard,
    render_help,
    render_inviter_selection,
    render_material_prompt,
    render_preview,
    render_submission_complete,
)
from bccy_bot.keyboards.callback_data import (
    parse_inviter_pick,
    parse_inviters_page,
)
from bccy_bot.keyboards.factory import (
    cancel_confirm_keyboard,
    existing_pending_keyboard,
    welcome_keyboard,
)
from bccy_bot.handlers.admin import (
    admin_mgmt as adm_mgmt_handlers,
    blacklist as adm_blacklist_handlers,
    channels as adm_channels_handlers,
    groups as adm_groups_handlers,
    inviters as adm_inviters_handlers,
    reimbursement as adm_rei_handlers,
    reimbursement_audit as adm_rev_handlers,
    settings_ui as adm_settings_handlers,
    teachers as adm_teachers_handlers,
)
from bccy_bot.handlers.inviter import audit as inviter_audit
from bccy_bot.handlers.user import recovery as recovery_handler
from bccy_bot.handlers.user import reimburse as reimburse_handler
from bccy_bot.repositories import application_repo, blacklist_repo
from bccy_bot.services import audit_service, wizard_service
from bccy_bot.services.wizard_service import CurrentStepInfo, WizardError
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()


# ---------- 内部工具 ----------


async def _send_current_step(update: Update, info: CurrentStepInfo, session) -> None:
    """根据 CurrentStepInfo 推送对应的 UI（新消息）。"""
    message = update.effective_message
    if message is None:
        return

    if info.is_inviter_selection:
        text, kb = await render_inviter_selection(session)
        await message.reply_text(text, reply_markup=kb)
        return

    if info.is_preview:
        materials = await wizard_service.list_submitted_materials(session, info.application)
        text, kb = render_preview(info, materials)
        await message.reply_text(text, reply_markup=kb)
        return

    text, kb = render_material_prompt(info)
    await message.reply_text(text, reply_markup=kb)


async def _ack(update: Update) -> None:
    """统一应答 callback query（避免转圈）。"""
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001
            pass


# ---------- 欢迎卡片相关 callback ----------


async def on_start_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[🚀 开始申请入群]"""
    await _ack(update)
    if update.effective_user is None:
        return
    user = update.effective_user

    async with session_scope(context) as session:
        if await blacklist_repo.is_blacklisted(session, user.id):
            if update.effective_message is not None:
                await update.effective_message.reply_text("❌ 您的账号已被限制使用本服务。")
            return

        try:
            application = await wizard_service.start_or_resume_application(
                session,
                applicant_telegram_id=user.id,
                applicant_username=user.username,
                applicant_display_name=user.full_name,
            )
        except WizardError as e:
            existing = await application_repo.get_active_for_user(session, user.id)
            if existing is not None and existing.status == APP_STATUS_PENDING:
                if update.effective_message is not None:
                    await update.effective_message.reply_text(
                        render_existing_pending(),
                        reply_markup=existing_pending_keyboard(),
                    )
                return
            if update.effective_message is not None:
                await update.effective_message.reply_text(f"⚠️ {e}")
            return

        info = await wizard_service.resolve_step(session, application)
        await _send_current_step(update, info, session)


async def on_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[❓ 帮助] 与 /help"""
    await _ack(update)
    if update.effective_message is not None:
        await update.effective_message.reply_text(render_help())


async def on_use_recovery_key_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """M0/M1 占位：M8 实现完整回群密钥流程。"""
    await _ack(update)
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            "🔑 回群密钥功能将在 M8 上线，敬请期待。"
        )


# ---------- 已有申请提示卡片 ----------


async def on_view_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[📋 查看进度]"""
    await _ack(update)
    if update.effective_user is None or update.effective_message is None:
        return

    async with session_scope(context) as session:
        app = await application_repo.get_active_for_user(session, update.effective_user.id)
        if app is None:
            await update.effective_message.reply_text(
                "您当前没有进行中的申请。", reply_markup=welcome_keyboard()
            )
            return
        if app.status == APP_STATUS_PENDING:
            await update.effective_message.reply_text(
                "🕒 状态：待审核\n您的申请已提交，正在等待审核。"
            )
            return
        info = await wizard_service.resolve_step(session, app)
        await _send_current_step(update, info, session)


async def on_cancel_and_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[🔄 取消并重新申请]"""
    await _ack(update)
    if update.effective_user is None or update.effective_message is None:
        return

    async with session_scope(context) as session:
        app = await application_repo.get_active_for_user(session, update.effective_user.id)
        if app is not None:
            await wizard_service.cancel_application(session, app)
        new_app = await wizard_service.start_or_resume_application(
            session,
            applicant_telegram_id=update.effective_user.id,
            applicant_username=update.effective_user.username,
            applicant_display_name=update.effective_user.full_name,
        )
        info = await wizard_service.resolve_step(session, new_app)
        await _send_current_step(update, info, session)


# ---------- Wizard 内导航 ----------


async def on_pick_inviter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return

    inviter_id = parse_inviter_pick(update.callback_query.data or "")
    if inviter_id is None:
        return

    async with session_scope(context) as session:
        app = await application_repo.get_active_for_user(session, update.effective_user.id)
        if app is None or app.status != APP_STATUS_WIZARD:
            if update.effective_message is not None:
                await update.effective_message.reply_text(
                    "当前没有正在进行中的申请，请 /start 重新开始。"
                )
            return
        try:
            info = await wizard_service.select_inviter(session, app, inviter_id)
        except WizardError as e:
            if update.effective_message is not None:
                await update.effective_message.reply_text(f"⚠️ {e}")
            return
        await _send_current_step(update, info, session)


async def on_inviters_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is None:
        return
    page = parse_inviters_page(update.callback_query.data or "")
    if page is None or page < 0:
        return
    async with session_scope(context) as session:
        text, kb = await render_inviter_selection(session, page=page)
    try:
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    except Exception:  # noqa: BLE001
        if update.effective_message is not None:
            await update.effective_message.reply_text(text, reply_markup=kb)


async def on_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None:
        return
    async with session_scope(context) as session:
        app = await application_repo.get_active_for_user(session, update.effective_user.id)
        if app is None or app.status != APP_STATUS_WIZARD:
            return
        info = await wizard_service.go_back(session, app)
        await _send_current_step(update, info, session)


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[❌ 取消申请] → 二次确认"""
    await _ack(update)
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            render_cancel_confirm(), reply_markup=cancel_confirm_keyboard()
        )


async def on_confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None or update.effective_message is None:
        return
    async with session_scope(context) as session:
        app = await application_repo.get_active_for_user(session, update.effective_user.id)
        if app is not None:
            await wizard_service.cancel_application(session, app)
    await update.effective_message.reply_text(
        "✅ 申请已取消。如需重新申请，请发送 /start。"
    )


async def on_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[« 不取消，继续]：抹掉二次确认卡片即可。"""
    await _ack(update)
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text("已返回当前步骤，请继续操作。")
        except Exception:  # noqa: BLE001
            pass


# ---------- 预览操作 ----------


async def on_preview_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None or update.effective_message is None:
        return
    async with session_scope(context) as session:
        app = await application_repo.get_active_for_user(session, update.effective_user.id)
        if app is None or app.status != APP_STATUS_WIZARD:
            await update.effective_message.reply_text("没有可提交的申请。")
            return
        try:
            await wizard_service.confirm_submit(session, app)
        except WizardError as e:
            await update.effective_message.reply_text(f"⚠️ {e}")
            return

        # 推送给审核者；失败不回滚 pending 状态（避免用户被卡住）
        try:
            await audit_service.notify_reviewers(session, context.bot, app)
        except Exception:  # noqa: BLE001
            log.exception("notify_reviewers_failed", application_id=app.id)

    await update.effective_message.reply_text(render_submission_complete())


async def on_preview_redo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None:
        return
    async with session_scope(context) as session:
        app = await application_repo.get_active_for_user(session, update.effective_user.id)
        if app is None or app.status != APP_STATUS_WIZARD:
            return
        try:
            info = await wizard_service.redo_materials(session, app)
        except WizardError as e:
            if update.effective_message is not None:
                await update.effective_message.reply_text(f"⚠️ {e}")
            return
        await _send_current_step(update, info, session)


# ---------- 收到用户消息（photo / text）：材料提交 ----------


async def on_material_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """私聊消息分发：按优先级让各模块消费 awaiting 输入，最后才落到 wizard 材料处理。"""
    if update.effective_user is None or update.message is None:
        return

    # 顺序消费各种 awaiting 状态
    # 报销审核者的等待状态置于最前：审核流程时效敏感（口令 5 分钟）
    consumers = (
        adm_rev_handlers.consume_payment_code_text,
        adm_rev_handlers.consume_reject_reason_text,
        inviter_audit.consume_reject_reason_text,
        recovery_handler.consume_recovery_key_text,
        adm_groups_handlers.consume_add_group_forward,
        adm_inviters_handlers.consume_add_inviter_text,
        adm_teachers_handlers.consume_text,
        adm_blacklist_handlers.consume_add_blacklist_text,
        adm_mgmt_handlers.consume_add_admin_text,
        adm_channels_handlers.consume_bind_channel_forward,
        adm_settings_handlers.consume_edit_ttl_text,
        adm_rei_handlers.consume_text,
        adm_rei_handlers.consume_eligibility_forward,
        # 报销 wizard 材料：要求用户已有 status='wizard' 的报销请求；不与申请人 wizard 冲突
        reimburse_handler.consume_material_message,
    )
    for c in consumers:
        if await c(update, context):
            return

    user = update.effective_user
    message = update.message

    async with session_scope(context) as session:
        app = await application_repo.get_active_for_user(session, user.id)
        if app is None or app.status != APP_STATUS_WIZARD:
            # 用户不在 wizard 中 —— 静默忽略，让其他 handler 处理
            return

        info = await wizard_service.resolve_step(session, app)
        if info.is_inviter_selection:
            await message.reply_text(
                "请先从下方按钮中选择一位邀请人。",
            )
            return
        if info.is_preview:
            await message.reply_text("已进入预览阶段，请使用下方按钮提交或重做。")
            return

        # 判定消息类型
        content_type = None
        telegram_file_id = None
        text_content = None
        if message.photo:
            content_type = CT_PHOTO
            # 取最高分辨率的 file_id（PTB photo 列表是按尺寸升序）
            telegram_file_id = message.photo[-1].file_id
        elif message.text and not message.text.startswith("/"):
            content_type = CT_TEXT
            text_content = message.text

        if content_type is None:
            await message.reply_text("不支持的消息类型，请按提示发送图片或文本。")
            return

        try:
            new_info = await wizard_service.submit_material(
                session,
                app,
                content_type=content_type,
                media_group_id=message.media_group_id,
                telegram_file_id=telegram_file_id,
                text_content=text_content,
                original_message_id=message.message_id,
            )
        except WizardError as e:
            await message.reply_text(f"⚠️ {e}")
            return

        await message.reply_text("✅ 已收到，下一步：")
        await _send_current_step(update, new_info, session)
