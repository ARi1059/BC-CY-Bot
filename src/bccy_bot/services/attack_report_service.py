"""
出击报告频道转发（[REQ §3.7]）。

严格边界：
- 仅转发 material_type='出击报告' 那条原始消息
- ❌ 不转发约课记录 / 上课手势图片
- ❌ 不附加任何元信息卡片
- ✅ 通过 forwardMessage 保留 Telegram 原生 "Forwarded from <用户>" 标签

每次尝试写一行 attack_report_forwards 表（status 记录"已发/失败/无报告/无频道"四种）。
失败不阻塞 approve 主流程；连续失败时由日志频道异常事件兜底告警。
"""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import BadRequest

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.application_material import ApplicationMaterial
from bccy_bot.db.models.attack_report_forward import AttackReportForward
from bccy_bot.db.models.enums import (
    ARF_FAILED,
    ARF_SENT,
    ARF_SKIPPED_NO_CHANNEL,
    ARF_SKIPPED_NO_REPORT,
    MAT_REPORT,
    SK_ATTACK_REPORT_CHANNEL_ID,
)
from bccy_bot.repositories import settings_repo
from bccy_bot.utils.retry import telegram_retry

log = structlog.get_logger()


async def _get_channel_id(session: AsyncSession) -> int | None:
    val = await settings_repo.get(session, SK_ATTACK_REPORT_CHANNEL_ID)
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        log.warning("attack_report_channel_id_malformed", value=val)
        return None


async def _find_report_material(
    session: AsyncSession, application_id: int
) -> ApplicationMaterial | None:
    result = await session.execute(
        select(ApplicationMaterial)
        .where(
            ApplicationMaterial.application_id == application_id,
            ApplicationMaterial.material_type == MAT_REPORT,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


@telegram_retry(max_attempts=3)
async def _forward(bot: Bot, *, chat_id: int, from_chat_id: int, message_id: int):
    return await bot.forward_message(
        chat_id=chat_id,
        from_chat_id=from_chat_id,
        message_id=message_id,
        disable_notification=True,
    )


async def forward_report(
    session: AsyncSession,
    bot: Bot,
    application: Application,
) -> AttackReportForward:
    """
    把申请人提交"出击报告"的原始消息直接转发到出击报告频道。

    无论结果如何都会写一行 attack_report_forwards 记录，方便后续审计/补发。
    """
    # 1. 频道未配置
    channel_id = await _get_channel_id(session)
    if channel_id is None:
        record = AttackReportForward(
            application_id=application.id,
            channel_id=None,
            telegram_message_id=None,
            status=ARF_SKIPPED_NO_CHANNEL,
            error=None,
            retry_count=0,
        )
        session.add(record)
        await session.flush()
        log.info("attack_report_skipped_no_channel", application_id=application.id)
        return record

    # 2. 申请未含出击报告材料
    report = await _find_report_material(session, application.id)
    if report is None:
        record = AttackReportForward(
            application_id=application.id,
            channel_id=channel_id,
            telegram_message_id=None,
            status=ARF_SKIPPED_NO_REPORT,
            error=None,
            retry_count=0,
        )
        session.add(record)
        await session.flush()
        log.info("attack_report_skipped_no_report_material", application_id=application.id)
        return record

    # 3. 尝试 forwardMessage（from_chat_id = 申请人私聊）
    try:
        forwarded = await _forward(
            bot,
            chat_id=channel_id,
            from_chat_id=application.applicant_telegram_id,
            message_id=report.original_message_id,
        )
        record = AttackReportForward(
            application_id=application.id,
            channel_id=channel_id,
            telegram_message_id=forwarded.message_id,
            status=ARF_SENT,
            error=None,
            retry_count=0,
        )
        session.add(record)
        await session.flush()
        log.info(
            "attack_report_forwarded",
            application_id=application.id,
            channel_id=channel_id,
            telegram_message_id=forwarded.message_id,
        )
        return record
    except BadRequest as e:
        record = AttackReportForward(
            application_id=application.id,
            channel_id=channel_id,
            telegram_message_id=None,
            status=ARF_FAILED,
            error=str(e),
            retry_count=3,
        )
        session.add(record)
        await session.flush()
        log.error(
            "attack_report_forward_failed",
            application_id=application.id,
            err=str(e),
        )
        return record
    except Exception as e:  # noqa: BLE001
        record = AttackReportForward(
            application_id=application.id,
            channel_id=channel_id,
            telegram_message_id=None,
            status=ARF_FAILED,
            error=str(e),
            retry_count=3,
        )
        session.add(record)
        await session.flush()
        log.exception(
            "attack_report_forward_unexpected",
            application_id=application.id,
        )
        return record
