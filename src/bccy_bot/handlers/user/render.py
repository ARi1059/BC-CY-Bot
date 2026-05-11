"""根据 wizard 当前步骤渲染对应消息文本与按钮的辅助函数。"""

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardMarkup

from bccy_bot.db.models.application_material import ApplicationMaterial
from bccy_bot.db.models.enums import CT_PHOTO, CT_TEXT
from bccy_bot.keyboards.factory import (
    inviter_list_keyboard,
    material_step_keyboard,
    preview_keyboard,
)
from bccy_bot.repositories import inviter_repo
from bccy_bot.services.wizard_service import CurrentStepInfo


async def render_inviter_selection(session: AsyncSession, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    inviters = await inviter_repo.list_active(session)
    if not inviters:
        return (
            "⚠️ 当前没有可用的邀请人，请联系管理员开通。",
            InlineKeyboardMarkup([]),
        )
    text = (
        "📝 第 1 步：请选择您的邀请人\n"
        "─────────────────────────\n"
        "请从下方列表中选择您的邀请老师/组别。"
    )
    return text, inviter_list_keyboard(inviters, page=page)


def render_material_prompt(info: CurrentStepInfo) -> tuple[str, InlineKeyboardMarkup]:
    """收集材料阶段的提示文案 + 导航按钮。"""
    assert info.current_material_index is not None
    i = info.current_material_index + 1
    n = info.total_materials
    mt = info.current_material_type

    if info.expected_content_type == CT_PHOTO:
        action = f"请上传【{mt}】单张图片"
        hint = "⚠️ 严格单张提交，不要使用媒体组打包发送"
    elif info.expected_content_type == CT_TEXT:
        action = f"请发送【{mt}】的文本内容"
        hint = ""
    else:
        action = f"请提交【{mt}】"
        hint = ""

    text = (
        f"📝 第 2 步：材料提交 ({i}/{n})\n"
        "─────────────────────────\n"
        f"{action}\n"
    )
    if hint:
        text += f"\n{hint}"

    can_back = True  # 材料阶段任何时候都可以回退（第 1 项回退到选邀请人）
    return text, material_step_keyboard(can_go_back=can_back)


def render_preview(info: CurrentStepInfo, materials: list[ApplicationMaterial]) -> tuple[str, InlineKeyboardMarkup]:
    inviter = info.inviter
    lines = ["📝 第 3 步：预览与提交", "─────────────────────────"]
    if inviter is not None:
        lines.append(f"邀请人：{inviter.display_name} · {inviter.group_label}")
    lines.append("")
    lines.append("已提交材料：")
    for m in materials:
        icon = "🖼" if m.content_type == CT_PHOTO else "📝"
        body = ""
        if m.content_type == CT_TEXT and m.text_content:
            preview = m.text_content if len(m.text_content) <= 80 else m.text_content[:80] + "…"
            body = f"\n    {preview}"
        lines.append(f"  {icon} {m.material_type}{body}")

    lines.append("")
    lines.append("确认无误后请提交。")
    return "\n".join(lines), preview_keyboard()


def render_existing_pending() -> str:
    return (
        "ℹ️ 您当前已有一份待审核的申请。\n"
        "请等待审核结果，或选择取消该申请重新开始。"
    )


def render_existing_wizard() -> str:
    return (
        "ℹ️ 您当前有一份未完成的申请。\n"
        "请选择继续或取消重新开始。"
    )


def render_cancel_confirm() -> str:
    return "⚠️ 确认要取消当前申请吗？\n取消后已提交的材料将被清除。"


def render_blacklisted() -> str:
    return "❌ 您的账号已被限制使用本服务。如有疑问请联系管理员。"


def render_help() -> str:
    return (
        "❓ 帮助\n"
        "─────────────────────────\n"
        "• /start —— 启动/继续申请\n"
        "• 申请流程严格逐项提交，不支持媒体组\n"
        "• 任何步骤都可使用按钮取消或返回上一步\n"
        "• 审核通过后您将收到一次性入群链接 + 回群密钥\n"
        "  请妥善保存回群密钥，账号丢失时可救济"
    )


def render_submission_complete() -> str:
    return (
        "✅ 申请已提交！\n"
        "─────────────────────────\n"
        "正在等待审核人处理，请耐心等待。\n"
        "审核通过后您将自动收到入群链接。"
    )
