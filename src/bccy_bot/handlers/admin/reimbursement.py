"""[💰 报销管理] —— 系统配置 / 资格列表 / 用户冷却覆盖 三大子模块。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin, require_super
from bccy_bot.keyboards.admin_callbacks import (
    parse_rei_elig_remove,
    parse_rei_elig_remove_confirm,
    parse_rei_override_remove,
    parse_rei_override_remove_confirm,
)
from bccy_bot.keyboards.admin_factory import (
    eligibility_list_keyboard,
    eligibility_remove_confirm_keyboard,
    override_remove_confirm_keyboard,
    overrides_list_keyboard,
    reimbursement_main_keyboard,
    reimbursement_settings_keyboard,
)
from bccy_bot.repositories import (
    admin_repo,
    eligibility_chat_repo,
    reimbursement_override_repo,
    reimbursement_settings,
)
from bccy_bot.utils.awaiting import clear_awaiting, get_awaiting, set_awaiting
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()


# === awaiting state kinds ===
AWAIT_REI_AMOUNT = "rei_set_amount"
AWAIT_REI_BUDGET = "rei_set_budget"
AWAIT_REI_COOLDOWN = "rei_set_cooldown"
AWAIT_REI_RESET_DAY = "rei_set_reset_day"
AWAIT_REI_ELIG_FORWARD = "rei_elig_forward"
AWAIT_REI_OVERRIDE_INPUT = "rei_override_input"


# ---------- 主面板 ----------


async def on_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, is_super = await require_admin(update, context)
    if not is_admin:
        return

    async with session_scope(context) as session:
        enabled = await reimbursement_settings.is_enabled(session)
        amount = await reimbursement_settings.get_fixed_amount_cents(session)
        budget = await reimbursement_settings.get_monthly_budget_cents(session)
        remaining = await reimbursement_settings.get_monthly_remaining_cents(session)
        cd = await reimbursement_settings.get_default_cooldown_days(session)
        reset_day = await reimbursement_settings.get_reset_day(session)
        elig_count = len(await eligibility_chat_repo.list_active(session))

    enabled_label = "✅ 已开启" if enabled else "⏸ 已关闭"
    amount_s = reimbursement_settings.cents_to_yuan_display(amount)
    budget_s = reimbursement_settings.cents_to_yuan_display(budget)
    remaining_s = reimbursement_settings.cents_to_yuan_display(remaining)
    text = (
        "💰 报销管理\n"
        "─────────────────────────\n"
        f"总开关：{enabled_label}\n"
        f"固定金额：{amount_s} 元\n"
        f"月预算：{budget_s} 元（剩余 {remaining_s}）\n"
        f"冷却天数：{cd} 天\n"
        f"重置日：每月 {reset_day} 日\n"
        f"资格群/频道：{elig_count} 个"
    )
    await edit_or_reply(update, text, reply_markup=reimbursement_main_keyboard(is_super=is_super))


# ---------- 系统配置 ----------


async def on_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, is_super = await require_admin(update, context)
    if not is_admin:
        return

    async with session_scope(context) as session:
        enabled = await reimbursement_settings.is_enabled(session)
        amount = await reimbursement_settings.get_fixed_amount_cents(session)
        budget = await reimbursement_settings.get_monthly_budget_cents(session)
        remaining = await reimbursement_settings.get_monthly_remaining_cents(session)
        cd = await reimbursement_settings.get_default_cooldown_days(session)
        reset_day = await reimbursement_settings.get_reset_day(session)

    text = (
        "📋 报销系统配置\n"
        "─────────────────────────\n"
        f"总开关：{'✅ 已开启' if enabled else '⏸ 已关闭'}\n"
        f"固定金额：{reimbursement_settings.cents_to_yuan_display(amount)} 元\n"
        f"月预算：{reimbursement_settings.cents_to_yuan_display(budget)} 元\n"
        f"当前剩余：{reimbursement_settings.cents_to_yuan_display(remaining)} 元\n"
        f"冷却天数：{cd} 天\n"
        f"重置日：每月 {reset_day} 日"
    )
    if not is_super:
        text += "\n\nⓘ 仅超级管理员可修改配置项。"
    await edit_or_reply(
        update, text, reply_markup=reimbursement_settings_keyboard(is_super=is_super, enabled=enabled)
    )


async def on_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    async with session_scope(context) as session:
        enabled = await reimbursement_settings.is_enabled(session)
        await reimbursement_settings.set_enabled(session, not enabled)
        new_state = not enabled
    log.info("rei_enabled_toggled", new=new_state)
    await on_settings_panel(update, context)


async def on_set_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_REI_AMOUNT)
    await edit_or_reply(
        update,
        "✏️ 请发送每次报销的【固定金额】（元，可带 1 位小数，如 50 / 50.5 / 50.00）。\n发送 /cancel 取消。",
    )


async def on_set_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_REI_BUDGET)
    await edit_or_reply(
        update,
        "✏️ 请发送月预算（元，整数或最多 2 位小数）。\n"
        "设置后不会立即重置当前剩余，如需立即重置可点【♻️ 重置当前月余额】。\n"
        "发送 /cancel 取消。",
    )


async def on_reset_remaining(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    async with session_scope(context) as session:
        budget = await reimbursement_settings.get_monthly_budget_cents(session)
        await reimbursement_settings.set_monthly_remaining_cents(session, budget)
    log.info("rei_remaining_reset", to_cents=budget)
    await on_settings_panel(update, context)


async def on_set_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_REI_COOLDOWN)
    await edit_or_reply(
        update,
        f"✏️ 请发送默认冷却天数（{reimbursement_settings.MIN_COOLDOWN_DAYS}-"
        f"{reimbursement_settings.MAX_COOLDOWN_DAYS}）。\n发送 /cancel 取消。",
    )


async def on_set_reset_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_REI_RESET_DAY)
    await edit_or_reply(
        update,
        f"✏️ 请发送预算重置日（{reimbursement_settings.MIN_RESET_DAY}-"
        f"{reimbursement_settings.MAX_RESET_DAY}）。\n"
        "每月该日的 00:00 自动把【月剩余】重置为【月预算】。\n发送 /cancel 取消。",
    )


# ---------- 资格列表 ----------


async def on_eligibility_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, is_super = await require_admin(update, context)
    if not is_admin:
        return
    async with session_scope(context) as session:
        rows = await eligibility_chat_repo.list_all(session)

    active_n = sum(1 for r in rows if r.is_active)
    text = (
        f"🎯 资格群/频道（active {active_n} / 总 {len(rows)}）\n"
        "─────────────────────────\n"
        "申请报销时，用户必须是【全部 active 项】的成员。\n"
    )
    if not rows:
        text += "\n暂无；请点击【➕ 添加】将本 Bot 加入目标群/频道并转发任一条消息到此处。"
    await edit_or_reply(
        update, text, reply_markup=eligibility_list_keyboard(rows, is_super=is_super)
    )


async def on_eligibility_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_REI_ELIG_FORWARD)
    await edit_or_reply(
        update,
        "📥 请将目标【群组或频道】中的任一条消息**转发**到此处。\n"
        "Bot 须已是该群/频道的管理员，才能调用 getChatMember 校验。\n\n发送 /cancel 取消。",
    )


async def on_eligibility_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.callback_query is None:
        return
    eid = parse_rei_elig_remove(update.callback_query.data or "")
    if eid is None:
        return
    async with session_scope(context) as session:
        from bccy_bot.db.models.eligibility_chat import EligibilityChat

        e = await session.get(EligibilityChat, eid)
        if e is None:
            await edit_or_reply(update, "⚠️ 已不存在。")
            return
        label = e.name
    await edit_or_reply(
        update,
        f"⚠️ 确认从资格列表移除「{label}」？\n（移除后所有现有 active 行的成员将立即影响新申请的资格判定。）",
        reply_markup=eligibility_remove_confirm_keyboard(eid),
    )


async def on_eligibility_remove_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.callback_query is None:
        return
    eid = parse_rei_elig_remove_confirm(update.callback_query.data or "")
    if eid is None:
        return
    async with session_scope(context) as session:
        from bccy_bot.db.models.eligibility_chat import EligibilityChat

        e = await session.get(EligibilityChat, eid)
        if e is None:
            await edit_or_reply(update, "⚠️ 已不存在。")
            return
        await session.delete(e)
        await session.flush()
    log.info("rei_eligibility_removed", elig_id=eid)
    await edit_or_reply(update, "✅ 已移除。")


# ---------- 用户冷却覆盖 ----------


async def on_overrides_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    async with session_scope(context) as session:
        rows = await reimbursement_override_repo.list_all(session)
    text = (
        f"🛡 用户冷却覆盖（{len(rows)} 条）\n"
        "─────────────────────────\n"
        "对单个用户覆盖默认冷却天数。覆盖后该用户报销冷却以此为准。"
    )
    if not rows:
        text += "\n\n暂无覆盖。"
    await edit_or_reply(update, text, reply_markup=overrides_list_keyboard(rows))


async def on_override_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_REI_OVERRIDE_INPUT)
    await edit_or_reply(
        update,
        "✏️ 请按以下格式发送（一行）：\n\n"
        "`<telegram_user_id> <冷却天数> [备注]`\n\n"
        "示例：\n"
        "  `123456789 14 长期会员`\n"
        "  `987654321 3`\n\n"
        "发送 /cancel 取消。",
    )


async def on_override_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.callback_query is None:
        return
    oid = parse_rei_override_remove(update.callback_query.data or "")
    if oid is None:
        return
    async with session_scope(context) as session:
        from bccy_bot.db.models.reimbursement_user_override import ReimbursementUserOverride

        o = await session.get(ReimbursementUserOverride, oid)
        if o is None:
            await edit_or_reply(update, "⚠️ 已不存在。")
            return
        label = f"{o.telegram_user_id} · {o.cooldown_days}天"
    await edit_or_reply(
        update,
        f"⚠️ 确认删除覆盖 {label}？删除后该用户回退到默认冷却天数。",
        reply_markup=override_remove_confirm_keyboard(oid),
    )


async def on_override_remove_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.callback_query is None:
        return
    oid = parse_rei_override_remove_confirm(update.callback_query.data or "")
    if oid is None:
        return
    async with session_scope(context) as session:
        from bccy_bot.db.models.reimbursement_user_override import ReimbursementUserOverride

        o = await session.get(ReimbursementUserOverride, oid)
        if o is None:
            await edit_or_reply(update, "⚠️ 已不存在。")
            return
        await reimbursement_override_repo.remove(session, o)
    log.info("rei_override_removed", override_id=oid)
    await edit_or_reply(update, "✅ 已删除。")


# ---------- 文本输入消费器 ----------


async def consume_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """统一消费报销面板的等待输入。返回 True 表示已消费。"""
    if update.effective_user is None or update.message is None or update.message.text is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None:
        return False
    kind = state.get("kind")
    if kind not in (
        AWAIT_REI_AMOUNT,
        AWAIT_REI_BUDGET,
        AWAIT_REI_COOLDOWN,
        AWAIT_REI_RESET_DAY,
        AWAIT_REI_OVERRIDE_INPUT,
    ):
        return False

    text = update.message.text.strip()
    if text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text("已取消。")
        return True

    if kind == AWAIT_REI_AMOUNT:
        try:
            cents = reimbursement_settings.yuan_text_to_cents(text)
        except ValueError:
            await update.message.reply_text("⚠️ 金额格式错误。")
            return True
        async with session_scope(context) as session:
            await reimbursement_settings.set_fixed_amount_cents(session, cents)
        await update.message.reply_text(
            f"✅ 固定金额已设为 {reimbursement_settings.cents_to_yuan_display(cents)} 元。"
        )
        clear_awaiting(context, update.effective_user.id)
        return True

    if kind == AWAIT_REI_BUDGET:
        try:
            cents = reimbursement_settings.yuan_text_to_cents(text)
        except ValueError:
            await update.message.reply_text("⚠️ 金额格式错误。")
            return True
        async with session_scope(context) as session:
            await reimbursement_settings.set_monthly_budget_cents(session, cents)
        await update.message.reply_text(
            f"✅ 月预算已设为 {reimbursement_settings.cents_to_yuan_display(cents)} 元。\n"
            "如需立即把【月剩余】同步重置，请回到面板点【♻️ 重置当前月余额】。"
        )
        clear_awaiting(context, update.effective_user.id)
        return True

    if kind == AWAIT_REI_COOLDOWN:
        try:
            days = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ 请发送整数。")
            return True
        if not (reimbursement_settings.MIN_COOLDOWN_DAYS <= days <= reimbursement_settings.MAX_COOLDOWN_DAYS):
            await update.message.reply_text(
                f"⚠️ 必须在 {reimbursement_settings.MIN_COOLDOWN_DAYS}-"
                f"{reimbursement_settings.MAX_COOLDOWN_DAYS} 之间。"
            )
            return True
        async with session_scope(context) as session:
            await reimbursement_settings.set_default_cooldown_days(session, days)
        await update.message.reply_text(f"✅ 默认冷却天数已设为 {days} 天。")
        clear_awaiting(context, update.effective_user.id)
        return True

    if kind == AWAIT_REI_RESET_DAY:
        try:
            day = int(text)
        except ValueError:
            await update.message.reply_text("⚠️ 请发送整数。")
            return True
        if not (reimbursement_settings.MIN_RESET_DAY <= day <= reimbursement_settings.MAX_RESET_DAY):
            await update.message.reply_text(
                f"⚠️ 必须在 {reimbursement_settings.MIN_RESET_DAY}-"
                f"{reimbursement_settings.MAX_RESET_DAY} 之间。"
            )
            return True
        async with session_scope(context) as session:
            await reimbursement_settings.set_reset_day(session, day)
        await update.message.reply_text(f"✅ 预算重置日已设为每月 {day} 日。")
        clear_awaiting(context, update.effective_user.id)
        return True

    if kind == AWAIT_REI_OVERRIDE_INPUT:
        return await _consume_override_input(update, context, text)

    return False


async def _consume_override_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> bool:
    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        await update.message.reply_text("⚠️ 格式错误，至少需要 `<user_id> <days>`。")
        return True
    try:
        uid = int(parts[0])
        days = int(parts[1])
    except ValueError:
        await update.message.reply_text("⚠️ user_id 与 days 必须为整数。")
        return True
    if uid <= 0:
        await update.message.reply_text("⚠️ user_id 无效。")
        return True
    if not (reimbursement_settings.MIN_COOLDOWN_DAYS <= days <= reimbursement_settings.MAX_COOLDOWN_DAYS):
        await update.message.reply_text(
            f"⚠️ days 必须在 {reimbursement_settings.MIN_COOLDOWN_DAYS}-"
            f"{reimbursement_settings.MAX_COOLDOWN_DAYS} 之间。"
        )
        return True
    notes = parts[2] if len(parts) >= 3 else None

    async with session_scope(context) as session:
        adder = await admin_repo.find_by_telegram_user_id(session, update.effective_user.id)
        await reimbursement_override_repo.upsert(
            session,
            telegram_user_id=uid,
            cooldown_days=days,
            notes=notes,
            added_by=adder.id if adder else None,
        )
    log.info("rei_override_upserted", user_id=uid, days=days)
    await update.message.reply_text(f"✅ 已为用户 {uid} 设置冷却 {days} 天。")
    clear_awaiting(context, update.effective_user.id)
    return True


async def consume_eligibility_forward(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """消费"等待转发"状态：识别群/频道 chat_id 后添加到资格列表。"""
    if update.effective_user is None or update.message is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_REI_ELIG_FORWARD:
        return False

    msg = update.message
    if msg.text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await msg.reply_text("已取消添加资格。")
        return True

    fwd_chat = None
    if getattr(msg, "forward_from_chat", None):
        fwd_chat = msg.forward_from_chat
    elif getattr(msg, "forward_origin", None):
        origin = msg.forward_origin
        fwd_chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)

    if fwd_chat is None:
        await msg.reply_text("⚠️ 这不是一条转发自群/频道的消息。")
        return True

    chat_type = getattr(fwd_chat, "type", None)
    if chat_type not in ("group", "supergroup", "channel"):
        await msg.reply_text(f"⚠️ 不支持的会话类型：{chat_type}")
        return True

    async with session_scope(context) as session:
        existing = await eligibility_chat_repo.find_by_telegram_chat_id(session, fwd_chat.id)
        if existing is not None:
            if not existing.is_active:
                await eligibility_chat_repo.activate(session, existing)
                await msg.reply_text(f"♻️ 资格项「{existing.name}」已重新启用。")
            else:
                await msg.reply_text(f"ℹ️ 资格项「{existing.name}」已存在。")
        else:
            name = fwd_chat.title or f"Chat{fwd_chat.id}"
            e = await eligibility_chat_repo.create(
                session,
                telegram_chat_id=fwd_chat.id,
                chat_type=chat_type,
                name=name,
            )
            await msg.reply_text(
                f"✅ 已添加资格项：「{e.name}」 ({e.chat_type}, ID {e.telegram_chat_id})"
            )
            log.info("rei_eligibility_added", chat_id=e.telegram_chat_id, type=e.chat_type)

    clear_awaiting(context, update.effective_user.id)
    return True
