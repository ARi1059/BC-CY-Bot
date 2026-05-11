"""管理员全局统计：申请总数 / 各状态分布 / 链接 / 密钥 / 各邀请人通过率明细。"""

from telegram import Update
from telegram.ext import ContextTypes

from bccy_bot.db.models.enums import APP_STATUS_PENDING
from bccy_bot.handlers.admin._common import ack, edit_or_reply, require_admin
from bccy_bot.keyboards.admin_factory import back_only_keyboard
from bccy_bot.services import stats_service
from bccy_bot.utils.session import session_scope


_TOP_INVITERS = 10  # 通过率明细只展示前 10 名，避免超出 Telegram 消息长度


async def on_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ack(update)
    is_admin, _ = await require_admin(update, context)
    if not is_admin:
        return

    async with session_scope(context) as session:
        s = await stats_service.compute_global_stats(session)

    pending = s.by_status.get(APP_STATUS_PENDING, 0)
    rate = f"{s.approval_rate * 100:.1f}%" if s.approval_rate is not None else "—"
    use_rate = (
        f"{(s.used_links / s.total_links * 100):.1f}%"
        if s.total_links else "—"
    )

    lines = [
        "📊 全局统计",
        "─────────────────────────",
        f"申请总数：{s.total}",
        f"  待审核：{pending}",
        f"  已通过：{s.by_status.get('approved', 0)}",
        f"  已拒绝：{s.by_status.get('rejected', 0)}",
        f"  已取消：{s.by_status.get('cancelled', 0)}",
        f"  通过率：{rate}",
        "",
        f"邀请链接：{s.total_links} 个",
        f"  已使用：{s.used_links}（使用率 {use_rate}）",
        f"  异常入群：{s.anomaly_links}",
        "",
        f"回群密钥：active {s.keys_active} / used {s.keys_used} / "
        f"revoked {s.keys_revoked} / reset {s.keys_reset}",
    ]

    # 各邀请人明细：按 (申请数 desc, 通过率 desc) 排
    if s.per_inviter:
        ranked = sorted(
            s.per_inviter,
            key=lambda x: (-x.total, -(x.approval_rate or 0)),
        )[:_TOP_INVITERS]
        lines.append("")
        lines.append(f"📌 各邀请人（前 {len(ranked)} 名）")
        lines.append("─────────────────────────")
        for inv_s in ranked:
            ar = f"{inv_s.approval_rate * 100:.0f}%" if inv_s.approval_rate is not None else "—"
            lines.append(
                f"  {inv_s.inviter_display}：申请 {inv_s.total} / 通过率 {ar}"
            )

    await edit_or_reply(update, "\n".join(lines), reply_markup=back_only_keyboard())
