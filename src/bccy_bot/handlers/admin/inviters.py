"""邀请人管理：列表 / 添加（多步引导）/ 启停 / 移除。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.enums import MAT_BOOKING, MAT_GESTURE, MAT_REPORT, REVIEW_MODE_DELEGATED, REVIEW_MODE_SELF
from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin
from bccy_bot.keyboards.admin_callbacks import (
    ADM_INV_LIST,
    MAT_CODE_MAP,
    parse_inv_add_pick_grp,
    parse_inv_add_set_mode,
    parse_inv_add_toggle_mat,
    parse_inv_list_page,
    parse_inv_remove,
    parse_inv_remove_confirm,
    parse_inv_toggle,
)
from bccy_bot.keyboards.admin_factory import (
    inviter_add_step3_pick_group_keyboard,
    inviter_add_step4_pick_materials_keyboard,
    inviter_add_step5_pick_mode_keyboard,
    inviter_add_step6_confirm_keyboard,
    inviter_list_keyboard,
    inviter_remove_confirm_keyboard,
)
from bccy_bot.repositories import group_repo, inviter_repo
from bccy_bot.utils.awaiting import (
    clear_awaiting,
    get_awaiting,
    set_awaiting,
    update_awaiting_data,
)
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

AWAIT_KIND = "add_inviter"
# 步骤：
#  1 - 等待 telegram_user_id (text)
#  2 - 等待 display_name (text)
#  3 - 等待 group_label (text)
#  4 - 选目标群组 (callback)
#  5 - 选材料 (multi-select callback)
#  6 - 选审核模式 (callback)
#  7 - 确认 (callback)


# ---------- 列表 / 启停 / 移除 ----------


async def on_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return

    page = 0
    if update.callback_query is not None:
        parsed = parse_inv_list_page(update.callback_query.data or "")
        if parsed is not None:
            page = max(0, parsed)

    async with session_scope(context) as session:
        inviters = await inviter_repo.list_all(session)

    text = f"🎓 邀请人管理（{len(inviters)} 个）"
    if not inviters:
        text += "\n\n暂无邀请人。点击「➕ 添加邀请人」开始配置。"
    await edit_or_reply(update, text, reply_markup=inviter_list_keyboard(inviters, page=page))


async def on_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    inv_id = parse_inv_toggle(update.callback_query.data or "")
    if inv_id is None:
        return
    async with session_scope(context) as session:
        inv = await inviter_repo.get_by_id(session, inv_id)
        if inv is None:
            await edit_or_reply(update, "⚠️ 邀请人不存在。")
            return
        await inviter_repo.toggle_active(session, inv)
    # 刷新列表
    await on_list(update, context)


async def on_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    inv_id = parse_inv_remove(update.callback_query.data or "")
    if inv_id is None:
        return
    async with session_scope(context) as session:
        inv = await inviter_repo.get_by_id(session, inv_id)
        if inv is None:
            await edit_or_reply(update, "⚠️ 邀请人不存在。")
            return
        label = f"{inv.display_name} · {inv.group_label}"
    await edit_or_reply(
        update,
        f"⚠️ 确认删除邀请人？\n\n{label}\n\n注意：仅删除配置，不影响历史申请记录。",
        reply_markup=inviter_remove_confirm_keyboard(inv_id),
    )


async def on_remove_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None:
        return
    inv_id = parse_inv_remove_confirm(update.callback_query.data or "")
    if inv_id is None:
        return
    async with session_scope(context) as session:
        inv = await inviter_repo.get_by_id(session, inv_id)
        if inv is None:
            await edit_or_reply(update, "⚠️ 邀请人不存在。")
            return
        await inviter_repo.delete(session, inv)
    await edit_or_reply(update, "✅ 邀请人已删除。")
    log.info("inviter_deleted", inviter_id=inv_id)


# ---------- 添加 wizard ----------


async def on_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[➕ 添加邀请人]：进入 step 1（等 telegram_user_id 文本）。"""
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.effective_user is None:
        return

    set_awaiting(context, update.effective_user.id, AWAIT_KIND, {"step": 1})
    text = (
        "📝 添加邀请人 · 步骤 1/6\n"
        "─────────────────────────\n"
        "请发送邀请人的 **Telegram 数字 ID**（如 123456789）。\n"
        "若该邀请人为「挂名」（无 Telegram 账号），请发送 /skip。\n\n"
        "发送 /cancel 取消。"
    )
    await edit_or_reply(update, text)


async def _push_step3_group_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope(context) as session:
        groups = await group_repo.list_active(session)
    if not groups:
        if update.effective_message is not None:
            await update.effective_message.reply_text(
                "⚠️ 暂无可用群组。请先在「群组管理」添加群组后再来。"
            )
        return
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            "📝 步骤 4/6：选择关联的目标群组",
            reply_markup=inviter_add_step3_pick_group_keyboard(groups),
        )


async def _push_step4_material_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    state = get_awaiting(context, update.effective_user.id)
    selected = set(state["data"].get("materials", [])) if state else set()
    text = "📝 步骤 5/6：选择该组别所需材料（多选）"
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=inviter_add_step4_pick_materials_keyboard(selected)
            )
            return
        except Exception:  # noqa: BLE001
            pass
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            text, reply_markup=inviter_add_step4_pick_materials_keyboard(selected)
        )


async def _push_step5_mode_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📝 步骤 6/6：选择审核模式\n"
        "─────────────────────────\n"
        "👤 自审型：由该邀请人本人审核\n"
        "🏢 代审型：由管理员统一审核"
    )
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=inviter_add_step5_pick_mode_keyboard()
            )
            return
        except Exception:  # noqa: BLE001
            pass
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=inviter_add_step5_pick_mode_keyboard())


async def _push_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    state = get_awaiting(context, update.effective_user.id)
    if state is None:
        return
    d = state["data"]
    mode_label = "👤 自审型" if d.get("review_mode") == REVIEW_MODE_SELF else "🏢 代审型"
    materials = "、".join(d.get("materials", []))
    tg_id_str = str(d.get("telegram_user_id")) if d.get("telegram_user_id") else "（挂名）"

    text = (
        "📝 确认创建邀请人\n"
        "─────────────────────────\n"
        f"Telegram ID：{tg_id_str}\n"
        f"显示名：{d.get('display_name', '')}\n"
        f"组别：{d.get('group_label', '')}\n"
        f"目标群组：{d.get('group_name', '')} (ID {d.get('group_id', '')})\n"
        f"所需材料：{materials}\n"
        f"审核模式：{mode_label}"
    )
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=inviter_add_step6_confirm_keyboard())
            return
        except Exception:  # noqa: BLE001
            pass
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=inviter_add_step6_confirm_keyboard())


async def on_add_pick_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.callback_query is None or update.effective_user is None:
        return
    gid = parse_inv_add_pick_grp(update.callback_query.data or "")
    if gid is None:
        return
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND:
        return
    async with session_scope(context) as session:
        from bccy_bot.db.models.group import Group
        g = await session.get(Group, gid)
        if g is None or not g.is_active:
            await edit_or_reply(update, "⚠️ 群组不可用。")
            return
        group_name = g.name
    update_awaiting_data(context, update.effective_user.id, group_id=gid, group_name=group_name, step=5)
    await _push_step4_material_picker(update, context)


async def on_add_toggle_material(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if update.callback_query is None or update.effective_user is None:
        return
    raw = parse_inv_add_toggle_mat(update.callback_query.data or "")
    if raw is None:
        return
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND:
        return

    # 特殊：'_show' 实际是"进入下一步：模式选择"，但 callback_data 公用前缀
    # 这里独立处理
    if raw == "_show":
        return  # _show 由 set_mode 路径处理（见下）

    mat = MAT_CODE_MAP.get(raw)
    if mat is None:
        return
    selected = set(state["data"].get("materials", []))
    if mat in selected:
        selected.discard(mat)
    else:
        selected.add(mat)
    update_awaiting_data(context, update.effective_user.id, materials=sorted(selected))
    await _push_step4_material_picker(update, context)


async def on_add_set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """选 mode 按钮 (self/deleg) 与"下一步进入 mode 选择"共用前缀。"""
    await ack(update)
    if update.callback_query is None or update.effective_user is None:
        return
    raw = parse_inv_add_set_mode(update.callback_query.data or "")
    if raw is None:
        return
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND:
        return

    if raw == "_show":
        # 进入步骤 6 选择模式
        if not state["data"].get("materials"):
            await edit_or_reply(update, "⚠️ 请至少选择 1 项材料。")
            return
        update_awaiting_data(context, update.effective_user.id, step=6)
        await _push_step5_mode_picker(update, context)
        return

    if raw == "self":
        mode = REVIEW_MODE_SELF
    elif raw == "deleg":
        mode = REVIEW_MODE_DELEGATED
    else:
        return

    update_awaiting_data(context, update.effective_user.id, review_mode=mode, step=7)
    await _push_confirm(update, context)


async def on_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin or update.effective_user is None:
        return
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND:
        return
    d = state["data"]
    required = ["display_name", "group_label", "group_id", "materials", "review_mode"]
    if any(d.get(k) in (None, "", []) for k in required):
        await edit_or_reply(update, "⚠️ 配置不完整，请重新发起添加流程。")
        clear_awaiting(context, update.effective_user.id)
        return

    async with session_scope(context) as session:
        inv = await inviter_repo.create(
            session,
            telegram_user_id=d.get("telegram_user_id") or None,
            display_name=d["display_name"],
            group_label=d["group_label"],
            target_group_id=d["group_id"],
            required_materials=d["materials"],
            review_mode=d["review_mode"],
        )

    clear_awaiting(context, update.effective_user.id)
    await edit_or_reply(
        update,
        f"✅ 邀请人「{inv.display_name} · {inv.group_label}」已创建。",
    )
    log.info("inviter_created", inviter_id=inv.id)


async def on_add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if update.effective_user is not None:
        clear_awaiting(context, update.effective_user.id)
    await edit_or_reply(update, "已取消添加邀请人。")


# ---------- 文本输入分发：step 1/2/3 ----------


async def consume_add_inviter_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    if update.effective_user is None or update.message is None or update.message.text is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND:
        return False
    step = state["data"].get("step", 1)
    text = update.message.text.strip()

    if text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text("已取消添加邀请人。")
        return True

    if step == 1:
        if text == "/skip":
            update_awaiting_data(context, update.effective_user.id, telegram_user_id=None, step=2)
        else:
            try:
                uid = int(text)
                if uid <= 0:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("⚠️ 请发送数字 ID，或发送 /skip 跳过。")
                return True
            update_awaiting_data(context, update.effective_user.id, telegram_user_id=uid, step=2)
        await update.message.reply_text(
            "📝 步骤 2/6：请发送邀请人的【显示名】（如 张老师）。"
        )
        return True

    if step == 2:
        if len(text) > 64:
            await update.message.reply_text("⚠️ 显示名过长（≤ 64 字）。")
            return True
        update_awaiting_data(context, update.effective_user.id, display_name=text, step=3)
        await update.message.reply_text("📝 步骤 3/6：请发送【组别名称】（如 A组）。")
        return True

    if step == 3:
        if len(text) > 32:
            await update.message.reply_text("⚠️ 组别名过长（≤ 32 字）。")
            return True
        update_awaiting_data(context, update.effective_user.id, group_label=text, step=4)
        await _push_step3_group_picker(update, context)
        return True

    return False
