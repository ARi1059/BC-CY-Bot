"""
报销资格校验：用户必须是所有 active eligibility_chats 的成员（[REQ §8.5.7]）。

实现要点：
- 对每个 active 条目调 getChatMember，任一不在群即失败
- 成功结果缓存 5 分钟（避免 /reimburse 频繁打到 Telegram API）
- 失败不缓存（让用户加群后立即可用）
- 任何 API 异常 = 视为不在该群（保守）

无 active 条目时如何处理：[REQ §8.5.11] 规定"全员拒绝"——必须显式配置至少 1 个。
"""

import time
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import BadRequest, Forbidden

from bccy_bot.repositories import eligibility_chat_repo

log = structlog.get_logger()

_CACHE_KEY = "_eligibility_cache"
_CACHE_TTL_SEC = 300  # 5 分钟

_PRESENT_STATUSES = ("member", "administrator", "creator", "restricted")


@dataclass
class EligibilityResult:
    ok: bool
    missing_chat_names: list[str] = field(default_factory=list)
    error_chat_names: list[str] = field(default_factory=list)
    checked_chats: int = 0


def _bot_cache(bot_data: dict) -> dict[int, tuple[float, EligibilityResult]]:
    return bot_data.setdefault(_CACHE_KEY, {})


def _get_cached(bot_data: dict, user_id: int) -> EligibilityResult | None:
    cache = _bot_cache(bot_data)
    entry = cache.get(user_id)
    if entry is None:
        return None
    ts, result = entry
    if time.time() - ts > _CACHE_TTL_SEC:
        cache.pop(user_id, None)
        return None
    return result


def _put_cached(bot_data: dict, user_id: int, result: EligibilityResult) -> None:
    # 仅缓存通过结果；失败不缓存
    if result.ok:
        _bot_cache(bot_data)[user_id] = (time.time(), result)


def clear_cache_for_user(bot_data: dict, user_id: int) -> None:
    _bot_cache(bot_data).pop(user_id, None)


async def check_membership(
    session: AsyncSession,
    bot: Bot,
    *,
    user_id: int,
    bot_data: dict | None = None,
) -> EligibilityResult:
    if bot_data is not None:
        cached = _get_cached(bot_data, user_id)
        if cached is not None:
            return cached

    chats = await eligibility_chat_repo.list_active(session)
    if not chats:
        # 显式空列表 = 全员拒绝（管理员必须至少配置 1 个）
        return EligibilityResult(ok=False, missing_chat_names=[], checked_chats=0)

    missing: list[str] = []
    errored: list[str] = []
    for c in chats:
        try:
            member = await bot.get_chat_member(c.telegram_chat_id, user_id)
            status = getattr(member, "status", None)
            if status not in _PRESENT_STATUSES:
                missing.append(c.name)
        except BadRequest as e:
            msg = str(e).lower()
            if "user not found" in msg or "chat not found" in msg or "member" in msg:
                missing.append(c.name)
            else:
                errored.append(c.name)
                log.warning(
                    "eligibility_check_badrequest",
                    chat_id=c.telegram_chat_id,
                    user_id=user_id,
                    err=str(e),
                )
        except Forbidden as e:
            errored.append(c.name)
            log.warning(
                "eligibility_check_forbidden",
                chat_id=c.telegram_chat_id,
                user_id=user_id,
                err=str(e),
            )
        except Exception as e:  # noqa: BLE001
            errored.append(c.name)
            log.warning(
                "eligibility_check_unexpected",
                chat_id=c.telegram_chat_id,
                user_id=user_id,
                err=str(e),
            )

    result = EligibilityResult(
        ok=(not missing and not errored),
        missing_chat_names=missing,
        error_chat_names=errored,
        checked_chats=len(chats),
    )
    if bot_data is not None:
        _put_cached(bot_data, user_id, result)
    return result
