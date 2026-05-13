"""报销老师管理：列表 / 添加 / 启停 / 删除 / 改档位 / 改组别（[v1.0.0-beta.3]）。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.enums import (
    REI_TIER_DEFAULT_CENTS,
    REI_TIER_LABELS,
    REI_TIER_VALUES_CENTS,
)
from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin, require_super
from bccy_bot.keyboards.admin_callbacks import (
    ADM_TEA_LIST,
    parse_tea_add_pick_tier,
    parse_tea_list_page,
    parse_tea_remove,
    parse_tea_remove_confirm,
    parse_tea_set_group_open,
    parse_tea_set_tier_open,
    parse_tea_set_tier_value,
    parse_tea_toggle,
)
from bccy_bot.keyboards.admin_factory import (
    teacher_add_confirm_keyboard,
    teacher_add_pick_tier_keyboard,
    teacher_list_keyboard,
    teacher_remove_confirm_keyboard,
    teacher_tier_picker_keyboard,
)
from bccy_bot.keyboards.awaiting_keyboard import cancel_awaiting_keyboard
from bccy_bot.repositories import reimburse_teacher_repo
from bccy_bot.utils.awaiting import (
    clear_awaiting,
    get_awaiting,
    set_awaiting,
    update_awaiting_data,
)
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

AWAIT_KIND_ADD = "add_teacher"
AWAIT_KIND_SET_GROUP = "tea_set_group"

# 添加 wizard 步骤：
# 1 - 等待 telegram_username (text)
# 2 - 等待 display_name (text)
# 3 - 等待 group_label (text)
# 4 - 选 tier (callback) → confirm


# ---------- 列表 / 启停 / 删除 ----------


async def on_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return

    page = 0
    if update.callback_query is not None:
        parsed = parse_tea_list_page(update.callback_query.data or "")
        if parsed is not None:
            page = max(0, parsed)

    async with session_scope(context) as session:
        teachers = await reimburse_teacher_repo.list_all(session)

    text = f"👨‍🏫 报销老师管理（{len(teachers)} 位）"
    if not teachers:
        text += "\n\n暂无老师。点击「➕ 添加报销老师」开始配置。"
    await edit_or_reply(update, text, reply_markup=teacher_list_keyboard(teachers, page=page))


async def on_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    tid = parse_tea_toggle(update.callback_query.data or "")
    if tid is None:
        return
    async with session_scope(context) as session:
        t = await reimburse_teacher_repo.get_by_id(session, tid)
        if t is None:
            await edit_or_reply(update, "⚠️ 老师不存在。")
            return
        await reimburse_teacher_repo.toggle_active(session, t)
    await on_list(update, context)


async def on_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    tid = parse_tea_remove(update.callback_query.data or "")
    if tid is None:
        return
    async with session_scope(context) as session:
        t = await reimburse_teacher_repo.get_by_id(session, tid)
        if t is None:
            await edit_or_reply(update, "⚠️ 老师不存在。")
            return
        label = f"{t.display_name} · {t.group_label}"
    await edit_or_reply(
        update,
        f"⚠️ 确认删除老师？\n\n{label}\n\n注意：仅删除配置，历史报销记录中老师 username 仍以快照保留。",
        reply_markup=teacher_remove_confirm_keyboard(tid),
    )


async def on_remove_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    tid = parse_tea_remove_confirm(update.callback_query.data or "")
    if tid is None:
        return
    async with session_scope(context) as session:
        t = await reimburse_teacher_repo.get_by_id(session, tid)
        if t is None:
            await edit_or_reply(update, "⚠️ 老师不存在。")
            return
        await reimburse_teacher_repo.delete(session, t)
    await edit_or_reply(update, "✅ 老师已删除。")
    log.info("teacher_deleted", teacher_id=tid)


# ---------- 添加 wizard ----------


async def on_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.effective_user is None:
        return

    set_awaiting(context, update.effective_user.id, AWAIT_KIND_ADD, {"step": 1})
    text = (
        "📝 添加报销老师 · 步骤 1/4\n"
        "─────────────────────────\n"
        "请发送老师的 **Telegram username**（不含 @，如 alice_li）。"
    )
    await edit_or_reply(update, text, reply_markup=cancel_awaiting_keyboard())


async def _push_pick_tier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📝 步骤 4/4：选择报销档位\n"
        "─────────────────────────\n"
        "该老师每次报销发放金额。"
    )
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            text, reply_markup=teacher_add_pick_tier_keyboard()
        )


async def _push_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    state = get_awaiting(context, update.effective_user.id)
    if state is None:
        return
    d = state["data"]
    cents = int(d.get("reimbursement_tier_cents") or REI_TIER_DEFAULT_CENTS)
    tier_label = REI_TIER_LABELS.get(cents, f"{cents/100:.0f} 元")
    text = (
        "📝 确认创建报销老师\n"
        "─────────────────────────\n"
        f"Username：@{d.get('telegram_username', '')}\n"
        f"显示名：{d.get('display_name', '')}\n"
        f"组别：{d.get('group_label', '')}\n"
        f"报销档位：💰 {tier_label}"
    )
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=teacher_add_confirm_keyboard())
            return
        except Exception:  # noqa: BLE001
            pass
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=teacher_add_confirm_keyboard())


async def on_add_pick_tier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None or update.effective_user is None:
        return
    cents = parse_tea_add_pick_tier(update.callback_query.data or "")
    if cents is None or cents not in REI_TIER_VALUES_CENTS:
        return
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND_ADD:
        return
    update_awaiting_data(
        context, update.effective_user.id, reimbursement_tier_cents=cents, step=5
    )
    await _push_confirm(update, context)


async def on_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.effective_user is None:
        return
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND_ADD:
        return
    d = state["data"]
    required = ["telegram_username", "display_name", "group_label"]
    if any(d.get(k) in (None, "") for k in required):
        await edit_or_reply(update, "⚠️ 配置不完整，请重新发起添加流程。")
        clear_awaiting(context, update.effective_user.id)
        return
    cents = int(d.get("reimbursement_tier_cents") or REI_TIER_DEFAULT_CENTS)
    if cents not in REI_TIER_VALUES_CENTS:
        cents = REI_TIER_DEFAULT_CENTS

    async with session_scope(context) as session:
        existing = await reimburse_teacher_repo.find_by_username(
            session, d["telegram_username"]
        )
        if existing is not None:
            await edit_or_reply(
                update,
                f"⚠️ username @{d['telegram_username']} 已存在（id={existing.id}）。如需修改请先删除旧记录。",
            )
            clear_awaiting(context, update.effective_user.id)
            return
        t = await reimburse_teacher_repo.create(
            session,
            telegram_username=d["telegram_username"],
            display_name=d["display_name"],
            group_label=d["group_label"],
            reimbursement_tier_cents=cents,
        )

    clear_awaiting(context, update.effective_user.id)
    tier_label = REI_TIER_LABELS.get(cents, f"{cents/100:.0f} 元")
    await edit_or_reply(
        update,
        f"✅ 报销老师「{t.display_name} · {t.group_label}」已创建（@{t.telegram_username}，💰 {tier_label}）。",
    )
    log.info("teacher_created", teacher_id=t.id, tier_cents=cents)


async def on_add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if update.effective_user is not None:
        clear_awaiting(context, update.effective_user.id)
    await edit_or_reply(update, "已取消添加报销老师。")


# ---------- 调档位 ----------


async def on_set_tier_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    tid = parse_tea_set_tier_open(update.callback_query.data or "")
    if tid is None:
        return
    async with session_scope(context) as session:
        t = await reimburse_teacher_repo.get_by_id(session, tid)
        if t is None:
            await edit_or_reply(update, "⚠️ 老师不存在。")
            return
        current = REI_TIER_LABELS.get(
            t.reimbursement_tier_cents, f"{t.reimbursement_tier_cents/100:.0f} 元"
        )
        label = f"{t.display_name} · {t.group_label}"
    await edit_or_reply(
        update,
        f"💰 调整报销档位\n─────────────────────────\n老师：{label}\n当前：{current}\n\n请选择新档位（仅影响后续报销，不回溯进行中的申请）：",
        reply_markup=teacher_tier_picker_keyboard(tid),
    )


async def on_set_tier_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    parsed = parse_tea_set_tier_value(update.callback_query.data or "")
    if parsed is None:
        return
    tid, cents = parsed
    if cents not in REI_TIER_VALUES_CENTS:
        await edit_or_reply(update, "⚠️ 非法档位。")
        return
    async with session_scope(context) as session:
        t = await reimburse_teacher_repo.get_by_id(session, tid)
        if t is None:
            await edit_or_reply(update, "⚠️ 老师不存在。")
            return
        await reimburse_teacher_repo.update_tier(session, t, cents)
        label = f"{t.display_name} · {t.group_label}"
        tier_label = REI_TIER_LABELS[cents]
    log.info("teacher_tier_updated", teacher_id=tid, tier_cents=cents)
    await on_list(update, context)
    if update.callback_query is not None:
        try:
            await update.callback_query.answer(f"✅ {label} → {tier_label}", show_alert=False)
        except Exception:  # noqa: BLE001
            pass


# ---------- 改组别 ----------


async def on_set_group_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None or update.effective_user is None:
        return
    tid = parse_tea_set_group_open(update.callback_query.data or "")
    if tid is None:
        return
    async with session_scope(context) as session:
        t = await reimburse_teacher_repo.get_by_id(session, tid)
        if t is None:
            await edit_or_reply(update, "⚠️ 老师不存在。")
            return
        label = f"{t.display_name}（当前组别：{t.group_label}）"
    set_awaiting(
        context, update.effective_user.id, AWAIT_KIND_SET_GROUP, {"teacher_id": tid}
    )
    await edit_or_reply(
        update,
        f"🏷 修改组别\n─────────────────────────\n{label}\n\n请发送新的组别名（≤ 32 字）。",
        reply_markup=cancel_awaiting_keyboard(),
    )


# ---------- 消费等待文本（add wizard step 1-3 + set_group_open 输入新组别）----------


async def consume_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user is None or update.message is None or update.message.text is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None:
        return False
    kind = state.get("kind")
    if kind not in (AWAIT_KIND_ADD, AWAIT_KIND_SET_GROUP):
        return False

    text = update.message.text.strip()
    if text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text("已取消。")
        return True

    if kind == AWAIT_KIND_SET_GROUP:
        if len(text) > 32:
            await update.message.reply_text("⚠️ 组别名过长（≤ 32 字）。")
            return True
        tid = state["data"]["teacher_id"]
        async with session_scope(context) as session:
            t = await reimburse_teacher_repo.get_by_id(session, tid)
            if t is None:
                await update.message.reply_text("⚠️ 老师不存在。")
                clear_awaiting(context, update.effective_user.id)
                return True
            await reimburse_teacher_repo.update_group_label(session, t, text)
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text(f"✅ 组别已更新为「{text}」。")
        log.info("teacher_group_updated", teacher_id=tid, new_group=text)
        return True

    # AWAIT_KIND_ADD
    step = state["data"].get("step", 1)
    if step == 1:
        un = text.lstrip("@")
        if not un or len(un) > 64 or not all(c.isalnum() or c == "_" for c in un):
            await update.message.reply_text("⚠️ username 仅允许字母/数字/下划线，1–64 字符。")
            return True
        update_awaiting_data(context, update.effective_user.id, telegram_username=un, step=2)
        await update.message.reply_text(
            "📝 步骤 2/4：请发送老师【显示名】（如 张老师，≤ 64 字）。",
            reply_markup=cancel_awaiting_keyboard(),
        )
        return True
    if step == 2:
        if len(text) > 128:
            await update.message.reply_text("⚠️ 显示名过长（≤ 128 字）。")
            return True
        update_awaiting_data(context, update.effective_user.id, display_name=text, step=3)
        await update.message.reply_text(
            "📝 步骤 3/4：请发送【组别名】（如 A组，≤ 32 字）。",
            reply_markup=cancel_awaiting_keyboard(),
        )
        return True
    if step == 3:
        if len(text) > 32:
            await update.message.reply_text("⚠️ 组别名过长（≤ 32 字）。")
            return True
        update_awaiting_data(context, update.effective_user.id, group_label=text, step=4)
        await _push_pick_tier(update, context)
        return True

    return False
