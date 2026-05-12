"""管理员面板所有 Inline Keyboard 集中工厂。"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bccy_bot.db.models.admin import Admin
from bccy_bot.db.models.blacklist import Blacklist
from bccy_bot.db.models.enums import REI_TIER_LABELS, REI_TIER_VALUES_CENTS
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.inviter import Inviter
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
    ADM_REI,
    ADM_REI_APPROVED_LIST,
    ADM_REI_ELIG,
    ADM_REI_ELIG_ADD,
    ADM_REI_ELIG_REMOVE_CONFIRM_PREFIX,
    ADM_REI_ELIG_REMOVE_PREFIX,
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
    ADM_GRP_ADD,
    ADM_GRP_LIST,
    ADM_GRP_LIST_PREFIX,
    ADM_GRP_REMOVE_CONFIRM_PREFIX,
    ADM_GRP_REMOVE_PREFIX,
    ADM_INV_ADD,
    ADM_INV_ADD_CANCEL,
    ADM_INV_ADD_CONFIRM,
    ADM_INV_ADD_PICK_GRP_PREFIX,
    ADM_INV_ADD_PICK_TIER_PREFIX,
    ADM_INV_ADD_SET_MODE_PREFIX,
    ADM_INV_ADD_TOGGLE_MAT_PREFIX,
    ADM_INV_LIST,
    ADM_INV_LIST_PREFIX,
    ADM_INV_REMOVE_CONFIRM_PREFIX,
    ADM_INV_REMOVE_PREFIX,
    ADM_INV_SET_TIER_OPEN_PREFIX,
    ADM_INV_SET_TIER_VALUE_PREFIX,
    ADM_INV_TOGGLE_PREFIX,
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
    ADM_REPORT_CHANNEL,
    ADM_REPORT_CHANNEL_BIND,
    ADM_REPORT_CHANNEL_UNBIND,
    ADM_STATS,
    MAT_CODE_MAP,
    MAT_TO_CODE,
)

ITEMS_PER_PAGE = 6


def _pager(prefix: str, page: int, total: int) -> list[InlineKeyboardButton]:
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("« 上一页", callback_data=f"{prefix}{page - 1}"))
    if (page + 1) * ITEMS_PER_PAGE < total:
        nav.append(InlineKeyboardButton("下一页 »", callback_data=f"{prefix}{page + 1}"))
    return nav


def _back_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("« 返回管理面板", callback_data=ADM_BACK)]


# === 主面板 ===


def main_panel_keyboard(is_super: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("👥 群组管理", callback_data=ADM_GRP_LIST),
            InlineKeyboardButton("🎓 邀请人管理", callback_data=ADM_INV_LIST),
        ],
        [
            InlineKeyboardButton("🚫 黑名单管理", callback_data=ADM_BL_LIST),
            InlineKeyboardButton("👮 管理员管理", callback_data=ADM_MGMT_LIST),
        ],
        [
            InlineKeyboardButton("📡 日志频道", callback_data=ADM_LOG_CHANNEL),
            InlineKeyboardButton("📋 出击报告频道", callback_data=ADM_REPORT_CHANNEL),
        ],
        [
            InlineKeyboardButton("📥 待我审核", callback_data=ADM_PENDING),
            InlineKeyboardButton("📊 全局统计", callback_data=ADM_STATS),
        ],
        [
            InlineKeyboardButton("🔑 回群密钥", callback_data=ADM_KEYS),
            InlineKeyboardButton("💰 报销管理", callback_data=ADM_REI),
        ],
    ]
    if is_super:
        rows.append([InlineKeyboardButton("⚙️ 系统配置", callback_data=ADM_CONFIG)])
    return InlineKeyboardMarkup(rows)


# === Groups ===


def group_list_keyboard(groups: list[Group], page: int = 0) -> InlineKeyboardMarkup:
    start = page * ITEMS_PER_PAGE
    chunk = groups[start : start + ITEMS_PER_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    for g in chunk:
        rows.append(
            [
                InlineKeyboardButton(f"📌 {g.name}", callback_data=ADM_GRP_LIST),  # 详情按钮（未来扩展）
                InlineKeyboardButton("🗑 删除", callback_data=f"{ADM_GRP_REMOVE_PREFIX}{g.id}"),
            ]
        )
    pager = _pager(ADM_GRP_LIST_PREFIX, page, len(groups))
    if pager:
        rows.append(pager)
    rows.append([InlineKeyboardButton("➕ 添加群组", callback_data=ADM_GRP_ADD)])
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def group_remove_confirm_keyboard(group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认删除", callback_data=f"{ADM_GRP_REMOVE_CONFIRM_PREFIX}{group_id}")],
            [InlineKeyboardButton("« 不删除，返回", callback_data=ADM_GRP_LIST)],
        ]
    )


# === Inviters ===


def inviter_list_keyboard(inviters: list[Inviter], page: int = 0) -> InlineKeyboardMarkup:
    start = page * ITEMS_PER_PAGE
    chunk = inviters[start : start + ITEMS_PER_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    for inv in chunk:
        status_icon = "✅" if inv.is_active else "⏸"
        tier_label = REI_TIER_LABELS.get(inv.reimbursement_tier_cents, f"{inv.reimbursement_tier_cents/100:.0f}元")
        label = f"{status_icon} {inv.display_name} · {inv.group_label} · 💰{tier_label}"
        rows.append(
            [
                InlineKeyboardButton(label, callback_data=ADM_INV_LIST),
                InlineKeyboardButton(
                    "⏸停用" if inv.is_active else "▶️启用",
                    callback_data=f"{ADM_INV_TOGGLE_PREFIX}{inv.id}",
                ),
                InlineKeyboardButton("🗑", callback_data=f"{ADM_INV_REMOVE_PREFIX}{inv.id}"),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    f"💰 调档位（当前 {tier_label}）",
                    callback_data=f"{ADM_INV_SET_TIER_OPEN_PREFIX}{inv.id}",
                ),
            ]
        )
    pager = _pager(ADM_INV_LIST_PREFIX, page, len(inviters))
    if pager:
        rows.append(pager)
    rows.append([InlineKeyboardButton("➕ 添加邀请人", callback_data=ADM_INV_ADD)])
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def inviter_tier_picker_keyboard(inviter_id: int) -> InlineKeyboardMarkup:
    """编辑某邀请人档位的子键盘：三档 + 返回。"""
    rows: list[list[InlineKeyboardButton]] = []
    for cents in REI_TIER_VALUES_CENTS:
        rows.append(
            [
                InlineKeyboardButton(
                    f"💰 {REI_TIER_LABELS[cents]}",
                    callback_data=f"{ADM_INV_SET_TIER_VALUE_PREFIX}{inviter_id}:{cents}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("« 返回邀请人列表", callback_data=ADM_INV_LIST)])
    return InlineKeyboardMarkup(rows)


def inviter_remove_confirm_keyboard(inviter_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ 确认删除", callback_data=f"{ADM_INV_REMOVE_CONFIRM_PREFIX}{inviter_id}"
                )
            ],
            [InlineKeyboardButton("« 不删除，返回", callback_data=ADM_INV_LIST)],
        ]
    )


def inviter_add_step3_pick_group_keyboard(groups: list[Group]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"📌 {g.name}", callback_data=f"{ADM_INV_ADD_PICK_GRP_PREFIX}{g.id}")]
        for g in groups
    ]
    rows.append([InlineKeyboardButton("« 取消", callback_data=ADM_INV_ADD_CANCEL)])
    return InlineKeyboardMarkup(rows)


def inviter_add_step4_pick_materials_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code, mat in MAT_CODE_MAP.items():
        check = "☑️" if mat in selected else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{check} {mat}",
                    callback_data=f"{ADM_INV_ADD_TOGGLE_MAT_PREFIX}{code}",
                )
            ]
        )
    if selected:
        rows.append([InlineKeyboardButton("« 下一步：选择审核模式", callback_data=f"{ADM_INV_ADD_SET_MODE_PREFIX}_show")])
    rows.append([InlineKeyboardButton("« 取消", callback_data=ADM_INV_ADD_CANCEL)])
    return InlineKeyboardMarkup(rows)


def inviter_add_step5_pick_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👤 自审型（邀请人本人审核）", callback_data=f"{ADM_INV_ADD_SET_MODE_PREFIX}self")],
            [
                InlineKeyboardButton(
                    "🏢 代审型（由管理员统一审核）",
                    callback_data=f"{ADM_INV_ADD_SET_MODE_PREFIX}deleg",
                )
            ],
            [InlineKeyboardButton("« 取消", callback_data=ADM_INV_ADD_CANCEL)],
        ]
    )


def inviter_add_step6_pick_tier_keyboard() -> InlineKeyboardMarkup:
    """添加 wizard 步骤 7/7：选择该邀请人的报销档位。"""
    rows: list[list[InlineKeyboardButton]] = []
    for cents in REI_TIER_VALUES_CENTS:
        rows.append(
            [
                InlineKeyboardButton(
                    f"💰 {REI_TIER_LABELS[cents]}",
                    callback_data=f"{ADM_INV_ADD_PICK_TIER_PREFIX}{cents}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("« 取消", callback_data=ADM_INV_ADD_CANCEL)])
    return InlineKeyboardMarkup(rows)


def inviter_add_step7_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认创建", callback_data=ADM_INV_ADD_CONFIRM)],
            [InlineKeyboardButton("« 取消", callback_data=ADM_INV_ADD_CANCEL)],
        ]
    )


# === Blacklist ===


def blacklist_list_keyboard(rows_data: list[Blacklist], page: int = 0) -> InlineKeyboardMarkup:
    start = page * ITEMS_PER_PAGE
    chunk = rows_data[start : start + ITEMS_PER_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    for bl in chunk:
        reason = (bl.reason[:18] + "…") if bl.reason and len(bl.reason) > 18 else (bl.reason or "—")
        rows.append(
            [
                InlineKeyboardButton(f"🚫 {bl.telegram_user_id} · {reason}", callback_data=ADM_BL_LIST),
                InlineKeyboardButton("解除", callback_data=f"{ADM_BL_REMOVE_PREFIX}{bl.id}"),
            ]
        )
    pager = _pager(ADM_BL_LIST_PREFIX, page, len(rows_data))
    if pager:
        rows.append(pager)
    rows.append([InlineKeyboardButton("➕ 添加黑名单", callback_data=ADM_BL_ADD)])
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def blacklist_remove_confirm_keyboard(bl_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认解除", callback_data=f"{ADM_BL_REMOVE_CONFIRM_PREFIX}{bl_id}")],
            [InlineKeyboardButton("« 取消", callback_data=ADM_BL_LIST)],
        ]
    )


# === Admin management ===


def admin_list_keyboard(
    admins: list[Admin], viewer_is_super: bool, viewer_telegram_id: int
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for a in admins:
        is_self = a.telegram_user_id == viewer_telegram_id
        if a.role == "super":
            label = f"👑 超级管理员 · {a.display_name or a.telegram_user_id}"
            if viewer_is_super:
                # 超级管理员自己看到 [🔄 转让身份]（点击需输入目标 sub admin id）
                rows.append([InlineKeyboardButton(label, callback_data=ADM_MGMT_LIST)])
            else:
                rows.append([InlineKeyboardButton(label, callback_data=ADM_MGMT_LIST)])
        else:
            tag = "（我）" if is_self else ""
            label = f"🛡 副管理员 · {a.display_name or a.telegram_user_id}{tag}"
            row = [InlineKeyboardButton(label, callback_data=ADM_MGMT_LIST)]
            if viewer_is_super:
                row.append(
                    InlineKeyboardButton("🔄 提升", callback_data=f"{ADM_MGMT_TRANSFER_PREFIX}{a.id}")
                )
                row.append(InlineKeyboardButton("🗑", callback_data=f"{ADM_MGMT_REMOVE_PREFIX}{a.id}"))
            rows.append(row)
    if viewer_is_super:
        rows.append([InlineKeyboardButton("➕ 添加副管理员", callback_data=ADM_MGMT_ADD)])
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def admin_remove_confirm_keyboard(admin_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认移除", callback_data=f"{ADM_MGMT_REMOVE_CONFIRM_PREFIX}{admin_id}")],
            [InlineKeyboardButton("« 取消", callback_data=ADM_MGMT_LIST)],
        ]
    )


def admin_transfer_confirm_keyboard(admin_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ 确认转让超级管理员", callback_data=f"{ADM_MGMT_TRANSFER_CONFIRM_PREFIX}{admin_id}"
                )
            ],
            [InlineKeyboardButton("« 取消", callback_data=ADM_MGMT_LIST)],
        ]
    )


# === Channels ===


def channel_panel_keyboard(*, is_log: bool, bound_id: int | None) -> InlineKeyboardMarkup:
    bind_cb = ADM_LOG_CHANNEL_BIND if is_log else ADM_REPORT_CHANNEL_BIND
    unbind_cb = ADM_LOG_CHANNEL_UNBIND if is_log else ADM_REPORT_CHANNEL_UNBIND
    rows: list[list[InlineKeyboardButton]] = []
    if bound_id is None:
        rows.append([InlineKeyboardButton("➕ 绑定频道", callback_data=bind_cb)])
    else:
        rows.append([InlineKeyboardButton("🔄 更换频道", callback_data=bind_cb)])
        rows.append([InlineKeyboardButton("➖ 解绑", callback_data=unbind_cb)])
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


# === Config ===


def config_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ 修改邀请链接有效期", callback_data=ADM_CONFIG_EDIT_TTL)],
            _back_row(),
        ]
    )


# === Stats / Pending / Keys 占位 ===


def back_only_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_back_row()])


# === 通用 dismiss ===


def dismiss_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✕ 关闭", callback_data=ADM_DISMISS)]])


# === 报销系统（v2 §8.5） ===


def reimbursement_main_keyboard(is_super: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("📋 系统配置", callback_data=ADM_REI_SETTINGS)],
        [
            InlineKeyboardButton("📥 待审核", callback_data=ADM_REI_PENDING_LIST),
            InlineKeyboardButton("💸 待付款", callback_data=ADM_REI_APPROVED_LIST),
        ],
        [InlineKeyboardButton("📜 历史记录", callback_data=ADM_REI_HISTORY_LIST)],
        [InlineKeyboardButton("🎯 资格列表", callback_data=ADM_REI_ELIG)],
    ]
    if is_super:
        rows.append([InlineKeyboardButton("🛡 用户冷却覆盖", callback_data=ADM_REI_OVERRIDES)])
    rows.append(_back_row())
    return InlineKeyboardMarkup(rows)


def reimbursement_pending_list_keyboard(rows_data) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for r in rows_data[:20]:
        label = f"#R{r.id} · {r.applicant_username or r.applicant_telegram_id}"
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{ADM_REI_RESEND_AUDIT_PREFIX}{r.id}",
                ),
                InlineKeyboardButton(
                    "👁 重发",
                    callback_data=f"{ADM_REI_RESEND_AUDIT_PREFIX}{r.id}",
                ),
            ]
        )
    rows.append([InlineKeyboardButton("« 返回报销管理", callback_data=ADM_REI)])
    return InlineKeyboardMarkup(rows)


def reimbursement_approved_list_keyboard(rows_data) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for r in rows_data[:20]:
        label = f"#R{r.id} · {r.applicant_username or r.applicant_telegram_id}"
        rows.append(
            [
                InlineKeyboardButton(label, callback_data=ADM_REI_APPROVED_LIST),
                InlineKeyboardButton(
                    "💸 补发口令",
                    callback_data=f"{ADM_REI_RESEND_PAYMENT_PREFIX}{r.id}",
                ),
            ]
        )
    rows.append([InlineKeyboardButton("« 返回报销管理", callback_data=ADM_REI)])
    return InlineKeyboardMarkup(rows)


def reimbursement_history_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("« 返回报销管理", callback_data=ADM_REI)]]
    )


def reimbursement_settings_keyboard(is_super: bool, enabled: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_super:
        rows.append(
            [
                InlineKeyboardButton(
                    "⏸ 关闭总开关" if enabled else "▶️ 开启总开关",
                    callback_data=ADM_REI_TOGGLE,
                )
            ]
        )
        rows.append(
            [InlineKeyboardButton("✏️ 设置月预算", callback_data=ADM_REI_SET_BUDGET)]
        )
        rows.append(
            [InlineKeyboardButton("♻️ 重置当前月余额至月预算", callback_data=ADM_REI_RESET_REMAINING)]
        )
        rows.append(
            [InlineKeyboardButton("✏️ 设置冷却天数", callback_data=ADM_REI_SET_COOLDOWN)]
        )
        rows.append(
            [InlineKeyboardButton("✏️ 设置预算重置日", callback_data=ADM_REI_SET_RESET_DAY)]
        )
    rows.append([InlineKeyboardButton("« 返回报销管理", callback_data=ADM_REI)])
    return InlineKeyboardMarkup(rows)


def eligibility_list_keyboard(
    rows_data, is_super: bool, page: int = 0
) -> InlineKeyboardMarkup:
    start = page * ITEMS_PER_PAGE
    chunk = rows_data[start : start + ITEMS_PER_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    for e in chunk:
        type_icon = {"channel": "📋", "supergroup": "📌", "group": "📌"}.get(e.chat_type, "•")
        label = f"{type_icon} {e.name}"
        row = [InlineKeyboardButton(label, callback_data=ADM_REI_ELIG)]
        if is_super:
            row.append(
                InlineKeyboardButton("🗑", callback_data=f"{ADM_REI_ELIG_REMOVE_PREFIX}{e.id}")
            )
        rows.append(row)
    if is_super:
        rows.append([InlineKeyboardButton("➕ 添加资格群/频道（转发消息）", callback_data=ADM_REI_ELIG_ADD)])
    rows.append([InlineKeyboardButton("« 返回报销管理", callback_data=ADM_REI)])
    return InlineKeyboardMarkup(rows)


def eligibility_remove_confirm_keyboard(elig_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认删除", callback_data=f"{ADM_REI_ELIG_REMOVE_CONFIRM_PREFIX}{elig_id}")],
            [InlineKeyboardButton("« 取消", callback_data=ADM_REI_ELIG)],
        ]
    )


def overrides_list_keyboard(rows_data, page: int = 0) -> InlineKeyboardMarkup:
    start = page * ITEMS_PER_PAGE
    chunk = rows_data[start : start + ITEMS_PER_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    for o in chunk:
        notes = (o.notes[:18] + "…") if o.notes and len(o.notes) > 18 else (o.notes or "")
        label = f"🛡 {o.telegram_user_id} · {o.cooldown_days}天 · {notes}"
        rows.append(
            [
                InlineKeyboardButton(label, callback_data=ADM_REI_OVERRIDES),
                InlineKeyboardButton(
                    "🗑", callback_data=f"{ADM_REI_OVERRIDE_REMOVE_PREFIX}{o.id}"
                ),
            ]
        )
    rows.append([InlineKeyboardButton("➕ 添加/更新覆盖", callback_data=ADM_REI_OVERRIDE_ADD)])
    rows.append([InlineKeyboardButton("« 返回报销管理", callback_data=ADM_REI)])
    return InlineKeyboardMarkup(rows)


def override_remove_confirm_keyboard(override_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ 确认删除", callback_data=f"{ADM_REI_OVERRIDE_REMOVE_CONFIRM_PREFIX}{override_id}")],
            [InlineKeyboardButton("« 取消", callback_data=ADM_REI_OVERRIDES)],
        ]
    )
