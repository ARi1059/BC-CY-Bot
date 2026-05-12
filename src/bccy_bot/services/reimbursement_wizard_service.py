"""
报销 wizard 状态机（[REQ §8.5.3.2]，[v1.0.0-beta.3] 与入群审核解耦）。

wizard_step 编码：
- 1 = 等待选老师
- 2 = 等待约课记录（photo）
- 3 = 等待上课手势（photo）
- 4 = 等待出击报告（text）
- 5 = 预览

固定 3 项材料：约课记录(photo) / 上课手势(photo) / 出击报告(text)
服务层零 telegram.* 依赖，handler 拆解 Update 后调用。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.enums import (
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REI_STATUS_PENDING,
    REI_STATUS_WIZARD,
)
from bccy_bot.db.models.reimburse_teacher import ReimburseTeacher
from bccy_bot.db.models.reimbursement_material import ReimbursementMaterial
from bccy_bot.db.models.reimbursement_request import ReimbursementRequest
from bccy_bot.repositories import (
    reimburse_teacher_repo,
    reimbursement_override_repo,
    reimbursement_repo,
    reimbursement_settings,
)

log = structlog.get_logger()


# 固定 3 项，顺序即材料子步骤
MATERIALS_ORDER: list[str] = [MAT_BOOKING, MAT_GESTURE, MAT_REPORT]
MATERIAL_CONTENT_TYPE: dict[str, str] = {
    MAT_BOOKING: CT_PHOTO,
    MAT_GESTURE: CT_PHOTO,
    MAT_REPORT: CT_TEXT,
}

# step 编码常量（统一处理避免散落魔术数）
TEACHER_STEP = 1
FIRST_MATERIAL_STEP = 2
LAST_MATERIAL_STEP = FIRST_MATERIAL_STEP + len(MATERIALS_ORDER) - 1  # 4
PREVIEW_STEP = LAST_MATERIAL_STEP + 1  # 5
TOTAL_MATERIALS = len(MATERIALS_ORDER)  # 3


class ReimbursementWizardError(Exception):
    """业务层错误（用户操作不合规），handler 据此回复友好提示。"""


# ---------- 预校验结果 ----------


@dataclass
class PreCheckResult:
    ok: bool
    reason_code: str  # 'ok' | 'disabled' | 'has_active_request' | 'cooldown'
    user_message: str
    cooldown_days_remaining: int | None = None


async def precheck(
    session: AsyncSession,
    *,
    applicant_telegram_id: int,
) -> PreCheckResult:
    """
    报销发起前的预校验（v1.0.0-beta.3 起，已解耦入群审核）。

    资格群成员校验、月预算校验、老师档位分别在 handler / set_teacher 阶段完成，
    本函数只覆盖与"该用户能否开始一份新 wizard"相关的判定。
    """
    # 1. 总开关 + 月预算 > 0（最基本的"系统是否就绪"）
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

    # 2. 是否已有进行中的报销
    active = await reimbursement_repo.get_active_for_user(session, applicant_telegram_id)
    if active is not None:
        return PreCheckResult(
            ok=False,
            reason_code="has_active_request",
            user_message="您已有一份进行中的报销申请，请先完成或取消。",
        )

    # 3. 冷却时间（基于最近一次完成的报销）
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

    return PreCheckResult(ok=True, reason_code="ok", user_message="")


# ---------- 当前步骤元信息 ----------


@dataclass
class CurrentStepInfo:
    request: ReimbursementRequest
    is_teacher_select: bool
    current_material_index: int | None  # 0-based；None 表示在预览或选老师
    current_material_type: str | None
    expected_content_type: str | None
    is_preview: bool


def resolve_step(request: ReimbursementRequest) -> CurrentStepInfo:
    step = request.wizard_step
    if step == TEACHER_STEP:
        return CurrentStepInfo(
            request=request,
            is_teacher_select=True,
            current_material_index=None,
            current_material_type=None,
            expected_content_type=None,
            is_preview=False,
        )
    if step >= PREVIEW_STEP:
        return CurrentStepInfo(
            request=request,
            is_teacher_select=False,
            current_material_index=None,
            current_material_type=None,
            expected_content_type=None,
            is_preview=True,
        )
    idx = step - FIRST_MATERIAL_STEP
    mt = MATERIALS_ORDER[idx]
    return CurrentStepInfo(
        request=request,
        is_teacher_select=False,
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
) -> ReimbursementRequest:
    """precheck 通过后调用，进入 wizard_step=1（选老师），未选老师前 teacher_id/amount 为空。"""
    return await reimbursement_repo.create_wizard(
        session,
        applicant_telegram_id=applicant_telegram_id,
        applicant_username=applicant_username,
        applicant_display_name=applicant_display_name,
        amount_cents=0,
        teacher_id=None,
        teacher_username_snapshot=None,
    )


# ---------- 选老师 ----------


async def set_teacher(
    session: AsyncSession,
    request: ReimbursementRequest,
    *,
    teacher_id: int,
) -> ReimburseTeacher:
    """
    在 wizard_step=1 阶段把老师快照写入 request 并推进到 step=2（材料 1）。

    顺手做"月预算 >= 该老师档位"的校验（此时金额已确定）。
    """
    if request.status != REI_STATUS_WIZARD:
        raise ReimbursementWizardError("当前申请已不在编辑状态。")
    if request.wizard_step != TEACHER_STEP:
        raise ReimbursementWizardError("当前步骤已超过选老师，不允许重新选择。")

    teacher = await reimburse_teacher_repo.get_by_id(session, teacher_id)
    if teacher is None or not teacher.is_active:
        raise ReimbursementWizardError("所选老师不存在或已停用，请重新选择。")

    # 选定老师瞬间快照金额；月预算检查也只能在此时做
    amount = int(teacher.reimbursement_tier_cents)
    remaining_budget = await reimbursement_settings.get_monthly_remaining_cents(session)
    if remaining_budget < amount:
        raise ReimbursementWizardError(
            f"本月预算余额（{reimbursement_settings.cents_to_yuan_display(remaining_budget)} 元）"
            f"不足以支付该老师档位（{reimbursement_settings.cents_to_yuan_display(amount)} 元），"
            "请月初再试或换一位档位更低的老师。"
        )

    await reimbursement_repo.set_teacher(
        session,
        request,
        teacher_id=teacher.id,
        teacher_username=teacher.telegram_username,
        amount_cents=amount,
    )
    await reimbursement_repo.advance_step(session, request, FIRST_MATERIAL_STEP)
    return teacher


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
    if info.is_teacher_select:
        raise ReimbursementWizardError("请先选择报销老师。")
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
        # 退回到最后一项材料步骤
        await reimbursement_repo.advance_step(session, request, LAST_MATERIAL_STEP)
        return resolve_step(request)

    if info.is_teacher_select:
        # 选老师阶段是起点，无可退
        return info

    # 在某项材料步：
    if info.current_material_index == 0:
        # 第一项材料 → 退回选老师；清除老师快照 + 清掉所有已传材料
        await reimbursement_repo.clear_materials(session, request.id)
        await reimbursement_repo.set_teacher(
            session,
            request,
            teacher_id=0,  # 用 0 表示"清空"语义，set_teacher 内部处理
            teacher_username="",
            amount_cents=0,
        )
        # set_teacher 不接受 0；改为直接清字段
        request.teacher_id = None
        request.teacher_username_snapshot = None
        request.amount_cents = 0
        await reimbursement_repo.advance_step(session, request, TEACHER_STEP)
        return resolve_step(request)

    # 其他材料步：删最后一项材料并 step -= 1
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
    await reimbursement_repo.advance_step(session, request, FIRST_MATERIAL_STEP)
    return resolve_step(request)


async def confirm_submit(
    session: AsyncSession, request: ReimbursementRequest
) -> ReimbursementRequest:
    info = resolve_step(request)
    if not info.is_preview:
        raise ReimbursementWizardError("尚未完成所有材料提交，无法确认。")

    if request.teacher_id is None or request.amount_cents <= 0:
        raise ReimbursementWizardError("缺少老师信息，请回到第一步重选。")

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
