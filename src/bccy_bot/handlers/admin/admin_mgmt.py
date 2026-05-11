"""管理员管理：超管视图 / 副管视图 / 添加副管 / 移除副管 / 身份转让（全部仅 super 可写）。"""

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.admin import Admin
from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin, require_super
from bccy_bot.keyboards.admin_callbacks import (
    parse_adm_remove,
    parse_adm_remove_confirm,
    parse_adm_transfer,
    parse_adm_transfer_confirm,
)
from bccy_bot.keyboards.admin_factory import (
    admin_list_keyboard,
    admin_remove_confirm_keyboard,
    admin_transfer_confirm_keyboard,
)
from bccy_bot.repositories import admin_repo
from bccy_bot.utils.awaiting import clear_awaiting, get_awaiting, set_awaiting
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

AWAIT_KIND = "add_sub_admin"


async def on_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, is_super = await require_admin(update, context)
    if not is_admin or update.effective_user is None:
        return
    async with session_scope(context) as session:
        admins = await admin_repo.list_all(session)
    if is_super:
        header = "👮 管理员管理（超级管理员视图）\n你可以添加副管理员、移除、或将超级管理员身份转让。"
    else:
        header = (
            "👮 管理员列表（只读）\n"
            "─────────────────────────\n"
            "ⓘ 仅超级管理员可任命或卸任副管理员。"
        )
    await edit_or_reply(
        update,
        header,
        reply_markup=admin_list_keyboard(admins, viewer_is_super=is_super, viewer_telegram_id=update.effective_user.id),
    )


async def on_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.effective_user is None:
        return
    set_awaiting(context, update.effective_user.id, AWAIT_KIND)
    await edit_or_reply(
        update,
        "📝 添加副管理员\n请发送目标用户的 Telegram 数字 ID。\n发送 /cancel 取消。",
    )


async def on_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.callback_query is None:
        return
    aid = parse_adm_remove(update.callback_query.data or "")
    if aid is None:
        return
    async with session_scope(context) as session:
        a = await session.get(Admin, aid)
        if a is None or a.role == "super":
            await edit_or_reply(update, "⚠️ 无效操作。")
            return
        label = a.display_name or str(a.telegram_user_id)
    await edit_or_reply(
        update,
        f"⚠️ 确认移除副管理员 {label}？",
        reply_markup=admin_remove_confirm_keyboard(aid),
    )


async def on_remove_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.callback_query is None or update.effective_user is None:
        return
    aid = parse_adm_remove_confirm(update.callback_query.data or "")
    if aid is None:
        return
    async with session_scope(context) as session:
        a = await session.get(Admin, aid)
        if a is None or a.role == "super":
            await edit_or_reply(update, "⚠️ 无效操作。")
            return
        await admin_repo.remove_sub_admin(session, a, by_super_telegram_id=update.effective_user.id)
    await edit_or_reply(update, "✅ 已移除副管理员。")
    log.info("sub_admin_removed", admin_id=aid)


async def on_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[🔄 提升]：将该副管理员提升为超级管理员（自身降级为 sub）。"""
    await ack(update)
    if not await require_super(update, context):
        return
    if update.callback_query is None:
        return
    aid = parse_adm_transfer(update.callback_query.data or "")
    if aid is None:
        return
    async with session_scope(context) as session:
        target = await session.get(Admin, aid)
        if target is None or target.role == "super":
            await edit_or_reply(update, "⚠️ 无效目标。")
            return
        label = target.display_name or str(target.telegram_user_id)
    await edit_or_reply(
        update,
        f"⚠️ 确认将「{label}」提升为超级管理员？\n你将降级为副管理员，且操作不可撤销（需新超管再次转让才能回滚）。",
        reply_markup=admin_transfer_confirm_keyboard(aid),
    )


async def on_transfer_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    if not await require_super(update, context):
        return
    if update.callback_query is None or update.effective_user is None:
        return
    aid = parse_adm_transfer_confirm(update.callback_query.data or "")
    if aid is None:
        return
    async with session_scope(context) as session:
        target = await session.get(Admin, aid)
        if target is None or target.role == "super":
            await edit_or_reply(update, "⚠️ 无效目标。")
            return
        current_super = await admin_repo.get_super_admin(session)
        if current_super is None:
            await edit_or_reply(update, "⚠️ 系统未配置超级管理员。")
            return
        try:
            await admin_repo.transfer_super_admin(
                session,
                new_super=target,
                current_super=current_super,
                by_telegram_id=update.effective_user.id,
            )
        except ValueError as e:
            await edit_or_reply(update, f"⚠️ {e}")
            return
    await edit_or_reply(
        update,
        f"✅ 超级管理员身份已转让给「{target.display_name or target.telegram_user_id}」。",
    )
    log.info("super_admin_transferred", target_admin_id=aid)


async def consume_add_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user is None or update.message is None or update.message.text is None:
        return False
    state = get_awaiting(context, update.effective_user.id)
    if state is None or state.get("kind") != AWAIT_KIND:
        return False

    text = update.message.text.strip()
    if text == "/cancel":
        clear_awaiting(context, update.effective_user.id)
        await update.message.reply_text("已取消添加副管理员。")
        return True

    try:
        uid = int(text)
        if uid <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ 请发送有效的数字 ID。")
        return True

    async with session_scope(context) as session:
        # 权限再次校验（防同时被取消超管资格）
        adder = await admin_repo.find_by_telegram_user_id(session, update.effective_user.id)
        if adder is None or adder.role != "super":
            await update.message.reply_text("⛔ 仅超级管理员可添加。")
            clear_awaiting(context, update.effective_user.id)
            return True

        existing = await admin_repo.find_by_telegram_user_id(session, uid)
        if existing is not None:
            await update.message.reply_text("ℹ️ 该用户已是管理员，无需重复添加。")
            clear_awaiting(context, update.effective_user.id)
            return True

        await admin_repo.add_sub_admin(
            session, telegram_user_id=uid, display_name=None, added_by=adder.id
        )

    await update.message.reply_text(f"✅ 已添加副管理员（ID {uid}）。")
    clear_awaiting(context, update.effective_user.id)
    return True
