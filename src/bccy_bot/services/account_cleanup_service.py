"""
密钥使用后的原账号清理（[REQ §3.8.5]）。

决策表：
| 原账号状态     | 在群内 | 动作                                           |
|---------------|:----:|----------------------------------------------|
| 正常账号       | ✅   | 踢出（banChatMember + 立即 unbanChatMember）    |
| 正常账号       | ❌   | 无动作                                         |
| 已注销账号     | 任意 | 永久封禁（banChatMember 不解封）+ 写入本地黑名单 |

例外：
- 原账号是该群管理员/群主 → 不踢/不封，仅告警
- Bot 缺权限 → cleanup_action='failed_no_permission'，不阻塞主流程
- 状态判定不确定 → 按 normal 兜底（不做封禁）
"""

from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import BadRequest, Forbidden

from bccy_bot.db.models.blacklist import Blacklist
from bccy_bot.db.models.enums import (
    CLEANUP_BAN,
    CLEANUP_FAILED_NO_PERMISSION,
    CLEANUP_KICK,
    CLEANUP_SKIP_ADMIN,
    CLEANUP_SKIP_NOT_IN_GROUP,
    CLEANUP_STATUS_DEACTIVATED,
    CLEANUP_STATUS_NORMAL,
    CLEANUP_STATUS_UNKNOWN,
)
from bccy_bot.repositories import blacklist_repo
from bccy_bot.utils.retry import telegram_retry
from bccy_bot.utils.tg_user import probe_old_account

log = structlog.get_logger()


@dataclass
class CleanupResult:
    action: str  # CLEANUP_KICK / CLEANUP_BAN / CLEANUP_SKIP_* / CLEANUP_FAILED_NO_PERMISSION
    old_account_status: str  # CLEANUP_STATUS_NORMAL / DEACTIVATED / UNKNOWN
    summary: str  # 一句话人类可读，写入日志频道卡片


@telegram_retry(max_attempts=3)
async def _ban(bot: Bot, chat_id: int, user_id: int) -> None:
    # until_date=0 (默认) = 永久
    await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)


@telegram_retry(max_attempts=3)
async def _unban(bot: Bot, chat_id: int, user_id: int) -> None:
    await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)


async def cleanup_old_account(
    session: AsyncSession,
    bot: Bot,
    *,
    target_chat_telegram_id: int,
    old_owner_telegram_id: int,
) -> CleanupResult:
    """对原账号执行踢/封决策。无论结果如何都返回，不抛。"""
    account_status, in_group, is_admin = await probe_old_account(
        bot,
        target_chat_telegram_id=target_chat_telegram_id,
        old_user_telegram_id=old_owner_telegram_id,
    )

    # 例外 1：原账号是群管理员/群主 —— 不动它，转人工
    if is_admin:
        log.warning(
            "cleanup_skip_admin",
            chat_id=target_chat_telegram_id,
            user_id=old_owner_telegram_id,
        )
        return CleanupResult(
            action=CLEANUP_SKIP_ADMIN,
            old_account_status=account_status,
            summary="⚠️ 跳过清理：原账号为群组管理员",
        )

    # 注销账号：永久封禁 + 入本地黑名单（无论是否在群中）
    if account_status == CLEANUP_STATUS_DEACTIVATED:
        try:
            await _ban(bot, target_chat_telegram_id, old_owner_telegram_id)
        except (BadRequest, Forbidden) as e:
            log.error(
                "cleanup_ban_failed_no_permission",
                chat_id=target_chat_telegram_id,
                user_id=old_owner_telegram_id,
                err=str(e),
            )
            return CleanupResult(
                action=CLEANUP_FAILED_NO_PERMISSION,
                old_account_status=account_status,
                summary=f"⚠️ 清理失败：Bot 缺少权限（{e}）",
            )
        # 写本地黑名单（幂等）
        if not await blacklist_repo.is_blacklisted(session, old_owner_telegram_id):
            session.add(
                Blacklist(
                    telegram_user_id=old_owner_telegram_id,
                    reason="账号已注销，密钥使用后自动封禁",
                    added_by=None,
                )
            )
            await session.flush()
        log.info(
            "cleanup_banned_deactivated",
            chat_id=target_chat_telegram_id,
            user_id=old_owner_telegram_id,
        )
        return CleanupResult(
            action=CLEANUP_BAN,
            old_account_status=account_status,
            summary="✅ 已永久封禁原账号（账号已注销）",
        )

    # 正常账号 + 不在群内：无动作
    if not in_group:
        return CleanupResult(
            action=CLEANUP_SKIP_NOT_IN_GROUP,
            old_account_status=account_status,
            summary="➖ 无需清理（原账号未在群内）",
        )

    # 正常账号 + 在群内：踢出（ban → 立即 unban）
    try:
        await _ban(bot, target_chat_telegram_id, old_owner_telegram_id)
        await _unban(bot, target_chat_telegram_id, old_owner_telegram_id)
    except (BadRequest, Forbidden) as e:
        log.error(
            "cleanup_kick_failed_no_permission",
            chat_id=target_chat_telegram_id,
            user_id=old_owner_telegram_id,
            err=str(e),
        )
        return CleanupResult(
            action=CLEANUP_FAILED_NO_PERMISSION,
            old_account_status=account_status,
            summary=f"⚠️ 清理失败：Bot 缺少权限（{e}）",
        )

    log.info(
        "cleanup_kicked_normal",
        chat_id=target_chat_telegram_id,
        user_id=old_owner_telegram_id,
    )
    return CleanupResult(
        action=CLEANUP_KICK,
        old_account_status=account_status,
        summary="✅ 已踢出原账号（账号正常，曾在群内）",
    )
