"""邀请人面板 /panel：归属待审 + 个人统计 + 重发审核材料。"""

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.application import Application
from bccy_bot.keyboards.inviter_callbacks import (
    INV_PANEL,
    INV_PANEL_BACK,
    INV_PANEL_PENDING,
    INV_PANEL_REPOST_PREFIX,
    INV_PANEL_STATS,
    parse_repost,
)
from bccy_bot.repositories import inviter_repo
from bccy_bot.services import audit_service, stats_service
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()


async def _ack(update: Update) -> None:
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001
            pass


async def _edit_or_reply(update: Update, text: str, reply_markup=None) -> None:
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
            return
        except Exception:  # noqa: BLE001
            pass
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=reply_markup)


async def _resolve_inviter(update, context):
    if update.effective_user is None:
        return None
    async with session_scope(context) as session:
        return await inviter_repo.find_by_telegram_user_id(session, update.effective_user.id)


def _panel_keyboard(pending_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"📥 待审核列表 ({pending_count})", callback_data=INV_PANEL_PENDING)],
            [InlineKeyboardButton("📊 我的统计", callback_data=INV_PANEL_STATS)],
        ]
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("« 返回面板", callback_data=INV_PANEL_BACK)]])


# ---------- /panel 命令 ----------


async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    async with session_scope(context) as session:
        inv = await inviter_repo.find_by_telegram_user_id(session, update.effective_user.id)
        if inv is None:
            await update.effective_message.reply_text(
                "⛔ 您未被登记为任何邀请人。如有疑问请联系管理员。"
            )
            return
        if not inv.is_active:
            await update.effective_message.reply_text(
                "⚠️ 您的邀请人配置已停用，请联系管理员。"
            )
            return
        stats = await stats_service.compute_inviter_stats(session, inv)

    text = (
        f"🧑‍🏫 邀请人面板 · {inv.display_name}（{inv.group_label}）\n"
        "─────────────────────────\n"
        f"📥 归属我的申请：{stats.total}\n"
        f"  待审核：{stats.pending}\n"
        f"  已通过：{stats.approved}\n"
        f"  已拒绝：{stats.rejected}\n"
        f"  已取消：{stats.cancelled}"
    )
    await update.effective_message.reply_text(text, reply_markup=_panel_keyboard(stats.pending))


# ---------- 主面板回调（返回） ----------


async def on_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None:
        return
    async with session_scope(context) as session:
        inv = await inviter_repo.find_by_telegram_user_id(session, update.effective_user.id)
        if inv is None:
            await _edit_or_reply(update, "⛔ 您未被登记为任何邀请人。")
            return
        stats = await stats_service.compute_inviter_stats(session, inv)
    text = (
        f"🧑‍🏫 邀请人面板 · {inv.display_name}（{inv.group_label}）\n"
        "─────────────────────────\n"
        f"📥 归属我的申请：{stats.total}\n"
        f"  待审核：{stats.pending}\n"
        f"  已通过：{stats.approved}\n"
        f"  已拒绝：{stats.rejected}\n"
        f"  已取消：{stats.cancelled}"
    )
    await _edit_or_reply(update, text, reply_markup=_panel_keyboard(stats.pending))


# ---------- 待审核列表 ----------


async def on_pending_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None:
        return
    async with session_scope(context) as session:
        inv = await inviter_repo.find_by_telegram_user_id(session, update.effective_user.id)
        if inv is None:
            await _edit_or_reply(update, "⛔ 您未被登记为任何邀请人。")
            return
        pending = await stats_service.list_pending_for_inviter(session, inv.id)

    if not pending:
        await _edit_or_reply(
            update,
            "📥 待审核列表\n\n暂无待审核申请。",
            reply_markup=_back_keyboard(),
        )
        return

    lines = [f"📥 待审核列表 ({len(pending)} 条)\n─────────────────────────"]
    rows: list[list[InlineKeyboardButton]] = []
    for app in pending[:20]:  # 单页最多 20，避免超过 Telegram 消息体大小
        submitted = app.submitted_at.strftime("%m-%d %H:%M") if app.submitted_at else "—"
        username = f"@{app.applicant_username}" if app.applicant_username else f"({app.applicant_telegram_id})"
        lines.append(f"• #A{app.id} {username} · 提交于 {submitted}")
        rows.append(
            [
                InlineKeyboardButton(
                    f"👁 重发 #A{app.id}",
                    callback_data=f"{INV_PANEL_REPOST_PREFIX}{app.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("« 返回面板", callback_data=INV_PANEL_BACK)])
    await _edit_or_reply(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows))


# ---------- 我的统计 ----------


async def on_my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.effective_user is None:
        return
    async with session_scope(context) as session:
        inv = await inviter_repo.find_by_telegram_user_id(session, update.effective_user.id)
        if inv is None:
            await _edit_or_reply(update, "⛔ 您未被登记为任何邀请人。")
            return
        stats = await stats_service.compute_inviter_stats(session, inv)

    approval = (
        f"{stats.approval_rate * 100:.1f}%" if stats.approval_rate is not None else "—"
    )
    usage = (
        f"{stats.link_usage_rate * 100:.1f}%" if stats.link_usage_rate is not None else "—"
    )
    text = (
        f"📊 我的统计 · {stats.inviter_display}\n"
        "─────────────────────────\n"
        f"累计申请：{stats.total}\n"
        f"  待审核：{stats.pending}\n"
        f"  已通过：{stats.approved}\n"
        f"  已拒绝：{stats.rejected}\n"
        f"  已取消：{stats.cancelled}\n"
        f"通过率（通过/已决）：{approval}\n"
        "─────────────────────────\n"
        f"邀请链接签发：{stats.links_issued}\n"
        f"  已使用：{stats.links_used}\n"
        f"  使用率：{usage}"
    )
    await _edit_or_reply(update, text, reply_markup=_back_keyboard())


# ---------- 重发审核材料 ----------


async def on_repost_materials(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ack(update)
    if update.callback_query is None or update.effective_user is None:
        return
    app_id = parse_repost(update.callback_query.data or "")
    if app_id is None:
        return

    async with session_scope(context) as session:
        inv = await inviter_repo.find_by_telegram_user_id(session, update.effective_user.id)
        if inv is None:
            return
        app = await session.get(Application, app_id)
        if app is None or app.inviter_id != inv.id:
            await _edit_or_reply(update, "⚠️ 该申请不属于您或已不存在。")
            return
        await audit_service.repost_materials(
            session,
            context.bot,
            app,
            requester_telegram_id=update.effective_user.id,
        )
    log.info("inviter_panel_repost", inviter_telegram_id=update.effective_user.id, application_id=app_id)
