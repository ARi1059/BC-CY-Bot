"""
Wizard 状态机（DB-backed，崩溃可恢复）。

application.wizard_step 取值约定：
- 0 : 选择邀请人阶段（status='wizard'，inviter_id 仍为 NULL）
- i (1..N) : 等待提交第 i 项材料（N = len(inviter.required_materials)）
- N+1 : 预览阶段（所有材料已提交，等待确认/重做/取消）

服务层只接受/返回纯数据，不依赖 telegram.* 类型，便于单元测试。
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.application_material import ApplicationMaterial
from bccy_bot.db.models.enums import (
    APP_STATUS_PENDING,
    APP_STATUS_WIZARD,
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
)
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.repositories import application_repo, inviter_repo, material_repo


# 材料类型到内容类型的映射（来自 REQ §3.1.1 用户编辑：约课记录=图片，上课手势=图片，出击报告=文本）
MATERIAL_CONTENT_TYPE: dict[str, str] = {
    MAT_BOOKING: CT_PHOTO,
    MAT_GESTURE: CT_PHOTO,
    MAT_REPORT: CT_TEXT,
}


class WizardError(Exception):
    """业务层错误（用户操作不合规），handler 据此回复友好提示。"""


@dataclass
class CurrentStepInfo:
    """当前 wizard 步骤的元信息，供 handler 渲染 UI。"""

    application: Application
    inviter: Inviter | None
    total_materials: int  # 该邀请人配置的材料总数 N
    current_material_index: int | None  # 当前等待的材料下标 (0-based)；None 表示非材料步骤
    current_material_type: str | None  # 例如 '约课记录'
    expected_content_type: str | None  # 'photo' 或 'text'
    is_preview: bool
    is_inviter_selection: bool


async def resolve_step(session: AsyncSession, application: Application) -> CurrentStepInfo:
    """根据 application.wizard_step 解析当前所处步骤。"""
    if application.inviter_id is None or application.wizard_step == 0:
        return CurrentStepInfo(
            application=application,
            inviter=None,
            total_materials=0,
            current_material_index=None,
            current_material_type=None,
            expected_content_type=None,
            is_preview=False,
            is_inviter_selection=True,
        )

    inviter = await inviter_repo.get_by_id(session, application.inviter_id)
    if inviter is None:
        raise WizardError("关联邀请人不存在或已被删除，请重新申请。")

    materials = list(inviter.required_materials or [])
    n = len(materials)

    if application.wizard_step > n:
        return CurrentStepInfo(
            application=application,
            inviter=inviter,
            total_materials=n,
            current_material_index=None,
            current_material_type=None,
            expected_content_type=None,
            is_preview=True,
            is_inviter_selection=False,
        )

    idx = application.wizard_step - 1
    mt = materials[idx]
    return CurrentStepInfo(
        application=application,
        inviter=inviter,
        total_materials=n,
        current_material_index=idx,
        current_material_type=mt,
        expected_content_type=MATERIAL_CONTENT_TYPE.get(mt),
        is_preview=False,
        is_inviter_selection=False,
    )


async def start_or_resume_application(
    session: AsyncSession,
    applicant_telegram_id: int,
    applicant_username: str | None,
    applicant_display_name: str | None,
) -> Application:
    """
    用户点击 [🚀 开始申请入群]：
    - 若已有 wizard/pending 申请：抛 WizardError（同一申请人不允许并发申请）
    - 否则新建一份 wizard 状态的申请
    """
    existing = await application_repo.get_active_for_user(session, applicant_telegram_id)
    if existing is not None:
        if existing.status == APP_STATUS_PENDING:
            raise WizardError("您已有一份待审核的申请。请等待审核结果，或先取消该申请。")
        # status == wizard：直接复用
        return existing

    return await application_repo.create_wizard(
        session,
        applicant_telegram_id=applicant_telegram_id,
        applicant_username=applicant_username,
        applicant_display_name=applicant_display_name,
    )


async def select_inviter(session: AsyncSession, application: Application, inviter_id: int) -> CurrentStepInfo:
    """Step 1 → Step 2 进入材料收集第一项。"""
    if application.status != APP_STATUS_WIZARD:
        raise WizardError("当前申请已不在编辑状态。")

    inviter = await inviter_repo.get_by_id(session, inviter_id)
    if inviter is None or not inviter.is_active:
        raise WizardError("该邀请人不可用，请重新选择。")

    if not inviter.required_materials:
        # 邀请人未配置任何材料 —— 视为配置异常，拒绝继续
        raise WizardError("该邀请人尚未配置申请材料，请联系管理员。")

    await application_repo.set_inviter(session, application, inviter_id)
    return await resolve_step(session, application)


async def go_back(session: AsyncSession, application: Application) -> CurrentStepInfo:
    """
    [« 上一步] 行为：
    - 材料步骤 step=i (i>=1) → 删除已提交的最后一项材料并回到 step=i-1
    - 若 i=1：回到选择邀请人（清空 inviter_id 与材料）
    - 预览步骤 step=N+1 → 回到最后一项材料步骤
    - 选择邀请人阶段：无操作
    """
    info = await resolve_step(session, application)

    if info.is_inviter_selection:
        return info

    if info.is_preview:
        # 预览 → 最后一项材料
        new_step = info.total_materials
        await application_repo.advance_wizard_step(session, application, new_step)
        return await resolve_step(session, application)

    # 正常材料步骤
    assert info.current_material_index is not None
    if info.current_material_index == 0:
        # 第一项 → 清空已选 inviter，回到 Step 1
        application.inviter_id = None
        await application_repo.clear_materials(session, application.id)
        await application_repo.advance_wizard_step(session, application, 0)
        return await resolve_step(session, application)

    # 删除最后一项（即上一项已提交的材料），回退 step
    materials = await application_repo.list_materials(session, application.id)
    if materials:
        await session.delete(materials[-1])
        await session.flush()
    await application_repo.advance_wizard_step(session, application, application.wizard_step - 1)
    return await resolve_step(session, application)


async def submit_material(
    session: AsyncSession,
    application: Application,
    *,
    content_type: str,
    media_group_id: str | None,
    telegram_file_id: str | None,
    text_content: str | None,
    original_message_id: int,
) -> CurrentStepInfo:
    """
    收到用户消息后调用，严格 [REQ §3.1.1]：
    - 媒体组拒收
    - 类型不匹配 → 不前进
    - 通过 → 落库 + step+1
    """
    info = await resolve_step(session, application)

    if info.is_inviter_selection or info.is_preview:
        raise WizardError("当前不在材料提交阶段，请使用下方按钮操作。")

    if media_group_id is not None:
        raise WizardError("请单张提交，不要打包发送（不支持媒体组）。")

    expected = info.expected_content_type
    if expected != content_type:
        if expected == CT_PHOTO:
            raise WizardError(f"请上传【{info.current_material_type}】单张图片。")
        elif expected == CT_TEXT:
            raise WizardError(f"请发送【{info.current_material_type}】的文本内容。")
        else:
            raise WizardError("当前材料类型未知，请联系管理员。")

    if content_type == CT_PHOTO:
        if not telegram_file_id:
            raise WizardError("图片解析失败，请重新发送。")
        await material_repo.add_photo(
            session,
            application_id=application.id,
            material_type=info.current_material_type or "",
            telegram_file_id=telegram_file_id,
            original_message_id=original_message_id,
        )
    elif content_type == CT_TEXT:
        if not text_content or not text_content.strip():
            raise WizardError("内容不能为空，请重新发送。")
        await material_repo.add_text(
            session,
            application_id=application.id,
            material_type=info.current_material_type or "",
            text_content=text_content.strip(),
            original_message_id=original_message_id,
        )
    else:
        raise WizardError("不支持的消息类型。")

    # 前进一步
    new_step = application.wizard_step + 1
    await application_repo.advance_wizard_step(session, application, new_step)
    return await resolve_step(session, application)


async def confirm_submit(session: AsyncSession, application: Application) -> Application:
    """预览页 [✅ 确认提交] → status='pending'。"""
    info = await resolve_step(session, application)
    if not info.is_preview:
        raise WizardError("尚未完成所有材料提交，无法确认。")

    # 校验材料齐全
    materials = await application_repo.list_materials(session, application.id)
    expected_types = list(info.inviter.required_materials or []) if info.inviter else []
    submitted_types = [m.material_type for m in materials]
    if sorted(submitted_types) != sorted(expected_types):
        raise WizardError("材料校验失败，请重新提交。")

    await application_repo.submit(session, application)
    return application


async def redo_materials(session: AsyncSession, application: Application) -> CurrentStepInfo:
    """预览页 [✏️ 重新提交] → 清空材料，回到 step=1。"""
    info = await resolve_step(session, application)
    if not info.is_preview:
        raise WizardError("当前不在预览页，无法重新提交。")

    await application_repo.clear_materials(session, application.id)
    await application_repo.advance_wizard_step(session, application, 1)
    return await resolve_step(session, application)


async def cancel_application(session: AsyncSession, application: Application) -> None:
    """[❌ 取消申请] → status='cancelled'，保留记录便于审计。"""
    if application.status not in (APP_STATUS_WIZARD, APP_STATUS_PENDING):
        return  # 已是终态，幂等
    await application_repo.cancel(session, application)


async def list_submitted_materials(
    session: AsyncSession, application: Application
) -> list[ApplicationMaterial]:
    return await application_repo.list_materials(session, application.id)
