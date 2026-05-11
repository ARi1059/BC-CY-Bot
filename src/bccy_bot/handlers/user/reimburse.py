"""用户侧报销 wizard：/reimburse 命令 + 4 层预校验 + 引导式提交。"""

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.enums import CT_PHOTO, CT_TEXT, REI_STATUS_WIZARD
from bccy_bot.db.models.reimbursement_material import ReimbursementMaterial
from bccy_bot.db.models.reimbursement_request import ReimbursementRequest
from bccy_bot.keyboards.reimburse_callbacks import (
    REI_USER_BACK,
    REI_USER_CANCEL,
    REI_USER_CONFIRM_CANCEL,
    REI_USER_DISMISS,
    REI_USER_PREVIEW_CONFIRM,
    REI_USER_PREVIEW_REDO,
)
from bccy_bot.repositories import (
    blacklist_repo,
    reimbursement_repo,
    reimbursement_settings,
)
from bccy_bot.services import (
    eligibility_service,
    reimbursement_wizard_service as rei_wizard,
)
from bccy_bot.services.reimbursement_wizard_service import (
    CurrentStepInfo,
    ReimbursementWizardError,
)
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()


# ---------- 共用 ----------


async def _ack(update: Update) -> None:
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001
            pass


def _material_step_keyboard(can_go_back: bool) -> InlineKeyboardMarkup:
    nav: list[InlineKeyboardButton] = []
    if can_go_back:
        nav.append(InlineKeyboardButton("« 上一步", callback_data=REI_USER_BACK))
    nav.append(InlineKeyboardButton("❌ 取消申请", callback_data=REI_USER_CANCEL))
    return InlineKeyboardMarkup([nav])


def _preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认提交", callback_data=REI_USER_PREVIEW_CONFIRM)],
            [InlineKeyboardButton("✏️ 重新提交", callback_data=REI_USER_PREVIEW_REDO)],
            [InlineKeyboardButton("« 上一步", callback_data=REI_USER_BACK)],
            [InlineKeyboardButton("❌ 取消申请", callback_data=REI_USER_CANCEL)],
        ]
    )


def _cancel_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认取消", callback_data=REI_USER_CONFIRM_CANCEL)],
            [InlineKeyboardButton("« 不取消，继续", callback_data=REI_USER_DISMISS)],
        ]
    )


def _render_material_prompt(info: CurrentStepInfo) -> tuple[str, InlineKeyboardMarkup]:
    assert info.current_material_index is not None
    i = info.current_material_index + 1
    n = rei_wizard.TOTAL_STEPS
    mt = info.current_material_type
    if info.expected_content_type == CT_PHOTO:
        action = f"请上传【{mt}】单张图片"
        hint = "⚠️ 严格单张提交，不要使用媒体组打包发送"
    else:
        action = f"请发送【{mt}】的文本内容"
        hint = ""
    text = (
        f"💰 报销申请 · 材料提交 ({i}/{n})\n"
        "─────────────────────────\n"
        f"{action}\n"
    )
    if hint:
        text += f"\n{hint}"
    can_back = info.current_material_index > 0
    return text, _material_step_keyboard(can_back)


def _render_preview(
    request: ReimbursementRequest, materials: list[ReimbursementMaterial]
) -> tuple[str, InlineKeyboardMarkup]:
    amount_yuan = reimbursement_settings.cents_to_yuan_display(request.amount_cents)
    lines = [
        "💰 报销申请 · 预览与提交",
        "─────────────────────────",
        f"金额：{amount_yuan} 元",
        "",
        "已提交材料：",
    ]
    for m in materials:
        icon = "🖼" if m.content_type == CT_PHOTO else "📝"
        body = ""
        if m.content_type == CT_TEXT and m.text_content:
            preview = m.text_content if len(m.text_content) <= 80 else m.text_content[:80] + "…"
            body = f"\n    {preview}"
        lines.append(f"  {icon} {m.material_type}{body}")
    lines.append("")
    lines.append("确认无误后请提交，等待管理员审核。")
    return "\n".join(lines), _preview_keyboard()


async def _send_step(update: Update, info: CurrentStepInfo, materials_for_preview=None) -> None:
    msg = update.effective_message
    if msg is None:
        return
    if info.is_preview:
        if materials_for_preview is None:
            materials_for_preview = []
        text, kb = _render_preview(info.request, materials_for_preview)
    else:
        text, kb = _render_material_prompt(info)
    await msg.reply_text(text, reply_markup=kb)


# ---------- 入口：/reimburse + 欢迎卡片按钮 ----------


async def reimburse_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reimburse 命令入口（与欢迎卡片 [💰 申请报销] 共用底层逻辑）。"""
    if update.effective_user is None or update.effective_message is None:
        return
    await _enter_reimburse(update, context)


async def on_start_from_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """欢迎卡片 [💰 申请报销] callback。"""
    await _ack(update)
    await _enter_reimburse(update, context)


async def _enter_reimburse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """4 层预校验 → 创建 wizard → 显示第 1 步。"""
    user = update.effective_user
    if user is None or update.effective_message is None:
        return

    async with session_scope(context) as session:
        # 黑名单（独立于 precheck，与 /start 行为一致）
        if await blacklist_repo.is_blacklisted(session, user.id):
            await update.effective_message.reply_text("❌ 您的账号已被限制使用本服务。")
            return

        # 1-2-3-4：disabled / no_approved_app / has_active / cooldown / budget
        pre = await rei_wizard.precheck(session, applicant_telegram_id=user.id)

        # has_active 单独处理：用户已有进行中的报销 wizard → 直接续上
        if pre.reason_code == "has_active_request":
            active = await reimbursement_repo.get_active_for_user(session, user.id)
            if active is not None and active.status == REI_STATUS_WIZARD:
                info = rei_wizard.resolve_step(active)
                if info.is_preview:
                    materials = await reimbursement_repo.list_materials(session, active.id)
                    await _send_step(update, info, materials)
                else:
                    await _send_step(update, info)
                return
            # pending 状态：友好提示
            await update.effective_message.reply_text(pre.user_message)
            return

        if not pre.ok:
            await update.effective_message.reply_text(f"⚠️ {pre.user_message}")
            return

        # 资格群成员校验（需要 bot 实例 + bot_data 缓存）
        elig = await eligibility_service.check_membership(
            session,
            context.bot,
            user_id=user.id,
            bot_data=context.bot_data,
        )
        if not elig.ok:
            log.info(
                "reimburse_eligibility_failed",
                user_id=user.id,
                missing=elig.missing_chat_names,
                errored=elig.error_chat_names,
            )
            await update.effective_message.reply_text(
                "⚠️ 您不符合报销资格，请联系管理员。"
            )
            return

        # 全部通过 → 创建 wizard
        request = await rei_wizard.create_request(
            session,
            applicant_telegram_id=user.id,
            applicant_username=user.username,
            applicant_display_name=user.full_name,
            application_id=pre.application_id,
            fixed_amount_cents=pre.fixed_amount_cents,
        )
        info = rei_wizard.resolve_step(request)

    intro = (
        f"💰 报销申请开始\n"
        f"金额：{reimbursement_settings.cents_to_yuan_display(pre.fixed_amount_cents)} 元\n"
        f"请按提示提交 {rei_wizard.TOTAL_STEPS} 项材料。"
    )
    await update.effective_message.reply_text(intro)
    await _send_step(update, info)


# ---------- 取消 / 上一步 / 二次确认 ----------


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            "⚠️ 确认要取消当前报销申请吗？\n取消后已提交的材料将被清除。",
            reply_markup=_cancel_confirm_keyboard(),
        )


async def on_confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None or update.effective_message is None:
        return
    async with session_scope(context) as session:
        active = await reimbursement_repo.get_active_for_user(
            session, update.effective_user.id
        )
        if active is not None:
            await rei_wizard.cancel(session, active)
    await update.effective_message.reply_text(
        "✅ 报销申请已取消。如需重新申请，请发送 /reimburse。"
    )


async def on_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text("已返回当前步骤，请继续操作。")
        except Exception:  # noqa: BLE001
            pass


async def on_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None:
        return
    async with session_scope(context) as session:
        active = await reimbursement_repo.get_active_for_user(
            session, update.effective_user.id
        )
        if active is None or active.status != REI_STATUS_WIZARD:
            return
        info = await rei_wizard.go_back(session, active)
        materials = await reimbursement_repo.list_materials(session, active.id) if info.is_preview else None
    await _send_step(update, info, materials)


# ---------- 预览操作 ----------


async def on_preview_redo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None:
        return
    async with session_scope(context) as session:
        active = await reimbursement_repo.get_active_for_user(
            session, update.effective_user.id
        )
        if active is None or active.status != REI_STATUS_WIZARD:
            return
        try:
            info = await rei_wizard.redo_materials(session, active)
        except ReimbursementWizardError as e:
            if update.effective_message is not None:
                await update.effective_message.reply_text(f"⚠️ {e}")
            return
    await _send_step(update, info)


async def on_preview_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None or update.effective_message is None:
        return
    async with session_scope(context) as session:
        active = await reimbursement_repo.get_active_for_user(
            session, update.effective_user.id
        )
        if active is None or active.status != REI_STATUS_WIZARD:
            await update.effective_message.reply_text("没有可提交的报销申请。")
            return
        try:
            await rei_wizard.confirm_submit(session, active)
        except ReimbursementWizardError as e:
            await update.effective_message.reply_text(f"⚠️ {e}")
            return

        # TODO(M13)：触发管理员侧审核推送 reimbursement_audit_service.notify_admins(...)

    await update.effective_message.reply_text(
        "✅ 报销申请已提交！\n"
        "─────────────────────────\n"
        "正在等待管理员处理。审核通过后您会收到口令红包文本。"
    )


# ---------- 私聊消息消费器（材料提交） ----------


async def consume_material_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    检查用户是否在报销 wizard 状态，若是则消费此 photo/text 消息。
    返回 True 表示已消费，由 wizard.on_material_message dispatch 链调用。
    """
    if update.effective_user is None or update.message is None:
        return False

    async with session_scope(context) as session:
        active = await reimbursement_repo.get_active_for_user(
            session, update.effective_user.id
        )
        if active is None or active.status != REI_STATUS_WIZARD:
            return False

        info = rei_wizard.resolve_step(active)
        if info.is_preview:
            await update.message.reply_text("已进入预览阶段，请使用下方按钮提交或重做。")
            return True

        # 判定消息类型
        content_type: str | None = None
        file_id: str | None = None
        text_content: str | None = None
        if update.message.photo:
            content_type = CT_PHOTO
            file_id = update.message.photo[-1].file_id
        elif update.message.text and not update.message.text.startswith("/"):
            content_type = CT_TEXT
            text_content = update.message.text

        if content_type is None:
            await update.message.reply_text("不支持的消息类型，请按提示发送图片或文本。")
            return True

        try:
            new_info = await rei_wizard.submit_material(
                session,
                active,
                content_type=content_type,
                media_group_id=update.message.media_group_id,
                telegram_file_id=file_id,
                text_content=text_content,
                original_message_id=update.message.message_id,
            )
        except ReimbursementWizardError as e:
            await update.message.reply_text(f"⚠️ {e}")
            return True

        materials = (
            await reimbursement_repo.list_materials(session, active.id) if new_info.is_preview else None
        )

    await update.message.reply_text("✅ 已收到，下一步：")
    await _send_step(update, new_info, materials)
    return True
