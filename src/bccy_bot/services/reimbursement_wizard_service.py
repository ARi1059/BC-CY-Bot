"""
报销 wizard 状态机（[REQ §8.5.3.2]）。

固定 3 项材料：约课记录(photo) / 上课手势(photo) / 出击报告(text)
wizard_step 编码：
- 1 = 等待约课记录
- 2 = 等待上课手势
- 3 = 等待出击报告
- 4 = 预览

服务层零 telegram.* 依赖，handler 拆解 Update 后调用。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REI_STATUS_PENDING,
    REI_STATUS_WIZARD,
)
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.db.models.reimbursement_material import ReimbursementMaterial
from bccy_bot.db.models.reimbursement_request import ReimbursementRequest
from bccy_bot.repositories import (
    reimbursement_override_repo,
    reimbursement_repo,
    reimbursement_settings,
)

log = structlog.get_logger()


# 固定 3 项，顺序即步骤
MATERIALS_ORDER: list[str] = [MAT_BOOKING, MAT_GESTURE, MAT_REPORT]
MATERIAL_CONTENT_TYPE: dict[str, str] = {
    MAT_BOOKING: CT_PHOTO,
    MAT_GESTURE: CT_PHOTO,
    MAT_REPORT: CT_TEXT,
}
TOTAL_STEPS = len(MATERIALS_ORDER)  # 3


class ReimbursementWizardError(Exception):
    """业务层错误（用户操作不合规），handler 据此回复友好提示。"""


# ---------- 预校验结果 ----------


@dataclass
class PreCheckResult:
    ok: bool
    reason_code: str  # 'ok' | 'disabled' | 'no_approved_app' | 'eligibility_failed'
                     # | 'cooldown' | 'budget_insufficient' | 'has_active_request'
                     # | 'no_inviter_tier'
    user_message: str
    application_id: int | None = None  # ok 路径：使用的入群审核 application
    cooldown_days_remaining: int | None = None  # cooldown 路径
    amount_cents: int = 0  # 报销金额（来自申请人所属邀请人的档位）


async def precheck(
    session: AsyncSession,
    *,
    applicant_telegram_id: int,
) -> PreCheckResult:
    """
    报销发起前的 4 层预校验（[REQ §8.5.3.1]）。

    资格群成员校验在 handler 里单独完成（需要 bot 实例），不在此处。
    """
    # 1. 总开关
    enabled = await reimbursement_settings.is_enabled(session)
    if not enabled:
        return PreCheckResult(
            ok=False,
            reason_code="disabled",
            user_message="报销功能当前未启用，请联系管理员。",
        )

    monthly_budget = await reimbursement_settings.get_monthly_budget_cents(session)
    if monthly_budget <= 0:
        return PreCheckResult(
            ok=False,
            reason_code="disabled",
            user_message="报销功能尚未配置完成（月预算未设），请联系管理员。",
        )

    # 2. 必须有 approved 入群审核
    from sqlalchemy import select

    approved = (
        await session.execute(
            select(Application)
            .where(
                Application.applicant_telegram_id == applicant_telegram_id,
                Application.status == APP_STATUS_APPROVED,
            )
            .order_by(Application.reviewed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if approved is None:
        return PreCheckResult(
            ok=False,
            reason_code="no_approved_app",
            user_message="您尚未通过入群审核，无法申请报销。",
        )

    # 2.5 该申请对应的邀请人必须存在，并据此决定报销金额
    if approved.inviter_id is None:
        return PreCheckResult(
            ok=False,
            reason_code="no_inviter_tier",
            user_message="该入群申请缺少邀请人信息，无法确定报销金额，请联系管理员。",
        )
    inviter = await session.get(Inviter, approved.inviter_id)
    if inviter is None:
        return PreCheckResult(
            ok=False,
            reason_code="no_inviter_tier",
            user_message="该入群申请对应的邀请人已被删除，请联系管理员。",
        )
    amount_cents = int(inviter.reimbursement_tier_cents)

    # 3. 是否已有进行中的报销
    active = await reimbursement_repo.get_active_for_user(session, applicant_telegram_id)
    if active is not None:
        return PreCheckResult(
            ok=False,
            reason_code="has_active_request",
            user_message="您已有一份进行中的报销申请，请先完成或取消。",
            application_id=approved.id,
            amount_cents=amount_cents,
        )

    # 4. 冷却时间
    last = await reimbursement_repo.get_last_completed_for_user(session, applicant_telegram_id)
    if last is not None and last.reviewed_at is not None:
        override = await reimbursement_override_repo.find_for_user(session, applicant_telegram_id)
        cd_days = (
            override.cooldown_days
            if override is not None
            else await reimbursement_settings.get_default_cooldown_days(session)
        )
        deadline = last.reviewed_at + timedelta(days=cd_days)
        now = datetime.now(timezone.utc)
        if now < deadline:
            remaining = (deadline - now).total_seconds() / 86400.0
            return PreCheckResult(
                ok=False,
                reason_code="cooldown",
                user_message=(
                    f"您还需等待 {remaining:.1f} 天才能再次申请（冷却 {cd_days} 天）。"
                ),
                cooldown_days_remaining=int(remaining + 0.999),
            )

    # 5. 月预算是否足够再发一次
    remaining_budget = await reimbursement_settings.get_monthly_remaining_cents(session)
    if remaining_budget < amount_cents:
        return PreCheckResult(
            ok=False,
            reason_code="budget_insufficient",
            user_message=(
                f"本月预算余额（{reimbursement_settings.cents_to_yuan_display(remaining_budget)} 元）"
                f"不足以支付一次报销（{reimbursement_settings.cents_to_yuan_display(amount_cents)} 元），"
                "请月初再试。"
            ),
        )

    return PreCheckResult(
        ok=True,
        reason_code="ok",
        user_message="",
        application_id=approved.id,
        amount_cents=amount_cents,
    )


# ---------- 当前步骤元信息 ----------


@dataclass
class CurrentStepInfo:
    request: ReimbursementRequest
    current_material_index: int | None  # 0-based；None 表示在预览
    current_material_type: str | None
    expected_content_type: str | None
    is_preview: bool


def resolve_step(request: ReimbursementRequest) -> CurrentStepInfo:
    step = request.wizard_step
    if step > TOTAL_STEPS:
        return CurrentStepInfo(
            request=request,
            current_material_index=None,
            current_material_type=None,
            expected_content_type=None,
            is_preview=True,
        )
    idx = step - 1
    mt = MATERIALS_ORDER[idx]
    return CurrentStepInfo(
        request=request,
        current_material_index=idx,
        current_material_type=mt,
        expected_content_type=MATERIAL_CONTENT_TYPE[mt],
        is_preview=False,
    )


# ---------- 创建 wizard ----------


async def create_request(
    session: AsyncSession,
    *,
    applicant_telegram_id: int,
    applicant_username: str | None,
    applicant_display_name: str | None,
    application_id: int,
    amount_cents: int,
) -> ReimbursementRequest:
    """precheck 通过后调用。直接进入 wizard_step=1。amount_cents 来自该申请人邀请人的档位快照。"""
    return await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=applicant_telegram_id,
        applicant_username=applicant_username,
        applicant_display_name=applicant_display_name,
        application_id=application_id,
        amount_cents=amount_cents,
    )


# ---------- 材料提交 / 回退 / 重做 / 确认 ----------


async def submit_material(
    session: AsyncSession,
    request: ReimbursementRequest,
    *,
    content_type: str,
    media_group_id: str | None,
    telegram_file_id: str | None,
    text_content: str | None,
    original_message_id: int,
) -> CurrentStepInfo:
    if request.status != REI_STATUS_WIZARD:
        raise ReimbursementWizardError("当前申请已不在编辑状态。")

    info = resolve_step(request)
    if info.is_preview:
        raise ReimbursementWizardError("已进入预览阶段，请使用下方按钮提交或重做。")

    if media_group_id is not None:
        raise ReimbursementWizardError("请单张提交，不要打包发送（不支持媒体组）。")

    expected = info.expected_content_type
    if expected != content_type:
        if expected == CT_PHOTO:
            raise ReimbursementWizardError(
                f"请上传【{info.current_material_type}】单张图片。"
            )
        else:
            raise ReimbursementWizardError(
                f"请发送【{info.current_material_type}】的文本内容。"
            )

    if content_type == CT_PHOTO:
        if not telegram_file_id:
            raise ReimbursementWizardError("图片解析失败，请重新发送。")
        await reimbursement_repo.add_material(
            session,
            reimbursement_id=request.id,
            material_type=info.current_material_type or "",
            content_type=CT_PHOTO,
            telegram_file_id=telegram_file_id,
            text_content=None,
            original_message_id=original_message_id,
        )
    else:
        if not text_content or not text_content.strip():
            raise ReimbursementWizardError("内容不能为空，请重新发送。")
        await reimbursement_repo.add_material(
            session,
            reimbursement_id=request.id,
            material_type=info.current_material_type or "",
            content_type=CT_TEXT,
            telegram_file_id=None,
            text_content=text_content.strip(),
            original_message_id=original_message_id,
        )

    await reimbursement_repo.advance_step(session, request, request.wizard_step + 1)
    return resolve_step(request)


async def go_back(
    session: AsyncSession, request: ReimbursementRequest
) -> CurrentStepInfo:
    info = resolve_step(request)

    if info.is_preview:
        # 退回最后一项材料步骤
        await reimbursement_repo.advance_step(session, request, TOTAL_STEPS)
        return resolve_step(request)

    if info.current_material_index == 0:
        # 第一步无可退；handler 应当不显示 [« 上一步]
        return info

    materials = await reimbursement_repo.list_materials(session, request.id)
    if materials:
        await session.delete(materials[-1])
        await session.flush()
    await reimbursement_repo.advance_step(session, request, request.wizard_step - 1)
    return resolve_step(request)


async def redo_materials(
    session: AsyncSession, request: ReimbursementRequest
) -> CurrentStepInfo:
    info = resolve_step(request)
    if not info.is_preview:
        raise ReimbursementWizardError("当前不在预览页，无法重新提交。")
    await reimbursement_repo.clear_materials(session, request.id)
    await reimbursement_repo.advance_step(session, request, 1)
    return resolve_step(request)


async def confirm_submit(
    session: AsyncSession, request: ReimbursementRequest
) -> ReimbursementRequest:
    info = resolve_step(request)
    if not info.is_preview:
        raise ReimbursementWizardError("尚未完成所有材料提交，无法确认。")

    materials = await reimbursement_repo.list_materials(session, request.id)
    submitted_types = sorted([m.material_type for m in materials])
    if submitted_types != sorted(MATERIALS_ORDER):
        raise ReimbursementWizardError("材料校验失败，请重新提交。")

    await reimbursement_repo.submit(session, request)
    return request


async def cancel(session: AsyncSession, request: ReimbursementRequest) -> None:
    if request.status not in (REI_STATUS_WIZARD, REI_STATUS_PENDING):
        return  # 已是终态，幂等
    await reimbursement_repo.cancel(session, request)
