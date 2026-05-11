"""基础统计：申请总数 / 各状态分布 / 链接使用情况 / 密钥状态等（数字版，详细图表延后）。"""

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    APP_STATUS_PENDING,
    APP_STATUS_REJECTED,
    RK_ACTIVE,
    RK_REVOKED,
    RK_USED,
)
from bccy_bot.db.models.invite_link import InviteLink
from bccy_bot.db.models.recovery_key import RecoveryKey
from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin
from bccy_bot.keyboards.admin_factory import back_only_keyboard
from bccy_bot.utils.session import session_scope


async def on_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return

    async with session_scope(context) as session:
        # applications by status
        rows = (
            await session.execute(
                select(Application.status, func.count(Application.id)).group_by(Application.status)
            )
        ).all()
        by_status = {r[0]: r[1] for r in rows}

        # invite_links
        total_links = (await session.execute(select(func.count(InviteLink.id)))).scalar_one()
        used_links = (
            await session.execute(select(func.count(InviteLink.id)).where(InviteLink.is_used.is_(True)))
        ).scalar_one()
        anomaly_links = (
            await session.execute(
                select(func.count(InviteLink.id)).where(InviteLink.is_anomaly.is_(True))
            )
        ).scalar_one()

        # recovery keys
        key_rows = (
            await session.execute(
                select(RecoveryKey.status, func.count(RecoveryKey.id)).group_by(RecoveryKey.status)
            )
        ).all()
        keys = {r[0]: r[1] for r in key_rows}

    pending = by_status.get(APP_STATUS_PENDING, 0)
    approved = by_status.get(APP_STATUS_APPROVED, 0)
    rejected = by_status.get(APP_STATUS_REJECTED, 0)
    total = sum(by_status.values())
    rate = f"{(approved / total * 100):.1f}%" if total else "—"

    text = (
        "📊 全局统计\n"
        "─────────────────────────\n"
        f"申请总数：{total}\n"
        f"  待审核：{pending}\n"
        f"  已通过：{approved}\n"
        f"  已拒绝：{rejected}\n"
        f"  通过率：{rate}\n\n"
        f"邀请链接：{total_links} 个（已使用 {used_links}，异常 {anomaly_links}）\n"
        f"回群密钥：active {keys.get(RK_ACTIVE, 0)} / used {keys.get(RK_USED, 0)} / "
        f"revoked {keys.get(RK_REVOKED, 0)}"
    )
    await edit_or_reply(update, text, reply_markup=back_only_keyboard())
