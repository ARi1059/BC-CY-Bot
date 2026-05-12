"""回群密钥的生成、哈希、签发与验证消费（[REQ §3.8]）。"""

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import (
    CLEANUP_PENDING,
    RK_ACTIVE,
    RK_USED,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.recovery_key import RecoveryKey
from bccy_bot.repositories import (
    blacklist_repo,
    inviter_repo,
    recovery_key_repo,
)
from bccy_bot.services import (
    account_cleanup_service,
    invite_link_service,
    log_channel_service,
)

log = structlog.get_logger()

# Base32 字符集去除易混字符（[REQ §3.8.2]）
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 去除 0/O/1/I/L
_KEY_PREFIX = "BCCY"
_SEGMENT_LEN = 4
_SEGMENT_COUNT = 4  # 4 段 × 4 位 = 16 位有效字符（约 80 bits 熵）

_hasher = PasswordHasher()


def generate_key_plaintext() -> str:
    """生成 'BCCY-XXXX-XXXX-XXXX-XXXX' 格式明文。"""
    segments = []
    for _ in range(_SEGMENT_COUNT):
        seg = "".join(secrets.choice(_ALPHABET) for _ in range(_SEGMENT_LEN))
        segments.append(seg)
    return f"{_KEY_PREFIX}-" + "-".join(segments)


def hash_key(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_key(plaintext: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plaintext)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001
        return False


def key_prefix_display(plaintext: str) -> str:
    """返回 'BCCY-XXXX' 用于管理后台显示（前 9 个字符：'BCCY' + '-' + 4 位首段）。"""
    return plaintext[: len(_KEY_PREFIX) + 1 + _SEGMENT_LEN]


async def has_active_key(session: AsyncSession, application_id: int) -> bool:
    result = await session.execute(
        select(RecoveryKey.id)
        .where(
            RecoveryKey.application_id == application_id,
            RecoveryKey.status == RK_ACTIVE,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def issue_first_key(
    session: AsyncSession,
    application: Application,
) -> tuple[RecoveryKey, str] | None:
    """
    审核通过时签发首把密钥（[REQ §3.8.2]：每个申请仅一把当前有效密钥）。

    返回 (DB record, plaintext) 或 None（如果已有 active 密钥则不重复签发）。
    明文仅在此处返回一次，调用方需立刻发送给用户。
    """
    if await has_active_key(session, application.id):
        return None

    plaintext = generate_key_plaintext()
    record = RecoveryKey(
        application_id=application.id,
        owner_telegram_id=application.applicant_telegram_id,
        original_owner_telegram_id=application.applicant_telegram_id,
        key_hash=hash_key(plaintext),
        key_prefix=key_prefix_display(plaintext),
        status=RK_ACTIVE,
        previous_key_id=None,
        failed_attempts=0,
    )
    session.add(record)
    await session.flush()

    log.info(
        "recovery_key_issued",
        application_id=application.id,
        key_id=record.id,
        key_prefix=record.key_prefix,
    )
    return record, plaintext


async def issue_chained_key(
    session: AsyncSession,
    application: Application,
    *,
    owner_telegram_id: int,
    previous_key_id: int,
) -> tuple[RecoveryKey, str]:
    """密钥成功使用后给新持有人签发链式新密钥。"""
    plaintext = generate_key_plaintext()
    record = RecoveryKey(
        application_id=application.id,
        owner_telegram_id=owner_telegram_id,
        original_owner_telegram_id=application.applicant_telegram_id,
        key_hash=hash_key(plaintext),
        key_prefix=key_prefix_display(plaintext),
        status=RK_ACTIVE,
        previous_key_id=previous_key_id,
        failed_attempts=0,
    )
    session.add(record)
    await session.flush()
    return record, plaintext


# ---------- 7 条校验 + 消费 ----------


_FORMAT_RE = re.compile(r"^BCCY(?:-[A-Z2-9]{4}){4}$")
_KEY_FAIL_LIMIT = 5
_KEY_FAIL_WINDOW_HOURS = 1.0
_CLAIMER_SUCCESS_LIMIT = 3
_CLAIMER_WINDOW_HOURS = 24.0


@dataclass
class VerifyResult:
    success: bool
    reason_code: str  # success / invalid_format / not_found / same_id / blacklisted /
                     # inviter_inactive / rate_limited
    user_message: str
    # 成功路径产物（其他为 None）
    invite_link_url: str | None = None
    new_key_plaintext: str | None = None
    application_id: int | None = None
    inviter_display: str | None = None
    cleanup_summary: str | None = None
    matched_key_id: int | None = None


def is_valid_format(text: str) -> bool:
    return bool(_FORMAT_RE.match(text))


async def _find_matching_key(
    session: AsyncSession, plaintext: str
) -> RecoveryKey | None:
    """
    Argon2 哈希是随机盐 + 不可直接索引，所以遍历所有 active key 逐一 verify。
    在小规模系统下完全可接受；如未来 keys 数量过大可加 key_fingerprint 索引列。
    """
    for k in await recovery_key_repo.list_active_keys(session):
        if verify_key(plaintext, k.key_hash):
            return k
    return None


async def verify_and_consume(
    session: AsyncSession,
    bot: Bot,
    *,
    key_plaintext: str,
    claimer_telegram_id: int,
    claimer_username: str | None = None,
) -> VerifyResult:
    """
    7 条校验顺序（[REQ §3.8.4]）：
    1 格式 → 2 哈希存在且 active → 3 同 ID 拦截 → 4 黑名单 →
    5 邀请人激活 → 6 单密钥 1h/5 失败锁 → 7 单新 ID 24h/3 上限
    通过则：生成新链接 + 签发新密钥 + 标记旧密钥 used + 触发原账号清理 + 写 success attempt。
    """
    plaintext = key_plaintext.strip().upper()

    # Rule 1
    if not is_valid_format(plaintext):
        await recovery_key_repo.record_attempt(
            session, key_hash=None, attempted_by_telegram_id=claimer_telegram_id,
            result="invalid_format",
        )
        return VerifyResult(False, "invalid_format", "密钥格式不正确。")

    # Rule 2
    matched = await _find_matching_key(session, plaintext)
    if matched is None:
        await recovery_key_repo.record_attempt(
            session, key_hash=None, attempted_by_telegram_id=claimer_telegram_id,
            result="not_found",
        )
        # 不区分原因，防探测
        return VerifyResult(False, "not_found", "密钥无效、已使用或已撤销。")

    # Rule 3 — 核心防滥用（同 ID 拦截）
    if claimer_telegram_id == matched.owner_telegram_id:
        await recovery_key_repo.record_attempt(
            session, key_hash=matched.key_hash, attempted_by_telegram_id=claimer_telegram_id,
            result="same_id",
        )
        try:
            await log_channel_service.push_recovery_key_anomaly(
                session, bot,
                claimer_telegram_id=claimer_telegram_id,
                reason="同 ID 拦截：使用者与密钥原持有人 ID 一致",
            )
        except Exception:  # noqa: BLE001
            pass
        return VerifyResult(
            False, "same_id",
            "该密钥仅用于在更换账号时使用，您当前账号与原账号一致，无需使用密钥。如需重新生成请联系管理员。",
        )

    # Rule 4
    if await blacklist_repo.is_blacklisted(session, claimer_telegram_id):
        await recovery_key_repo.record_attempt(
            session, key_hash=matched.key_hash, attempted_by_telegram_id=claimer_telegram_id,
            result="blacklisted",
        )
        return VerifyResult(False, "blacklisted", "您已被列入黑名单。")

    # Rule 5
    application = await session.get(Application, matched.application_id)
    inviter = None
    if application is not None and application.inviter_id is not None:
        inviter = await inviter_repo.get_by_id(session, application.inviter_id)
    if application is None or inviter is None or not inviter.is_active:
        await recovery_key_repo.record_attempt(
            session, key_hash=matched.key_hash, attempted_by_telegram_id=claimer_telegram_id,
            result="inviter_inactive",
        )
        return VerifyResult(False, "inviter_inactive", "关联邀请人已停用，请联系管理员。")

    # Rule 6 — 单密钥 1h/5 失败锁
    fails = await recovery_key_repo.count_failed_for_key_within(
        session, key_hash=matched.key_hash, hours=_KEY_FAIL_WINDOW_HOURS,
    )
    if fails >= _KEY_FAIL_LIMIT:
        await recovery_key_repo.record_attempt(
            session, key_hash=matched.key_hash, attempted_by_telegram_id=claimer_telegram_id,
            result="rate_limited",
        )
        return VerifyResult(
            False, "rate_limited",
            "尝试次数过多，请 1 小时后再试 / 联系管理员重置。",
        )

    # Rule 7 — 单新 ID 24h/3 次成功上限
    successes = await recovery_key_repo.count_success_for_claimer_within(
        session, claimer_telegram_id=claimer_telegram_id, hours=_CLAIMER_WINDOW_HOURS,
    )
    if successes >= _CLAIMER_SUCCESS_LIMIT:
        await recovery_key_repo.record_attempt(
            session, key_hash=matched.key_hash, attempted_by_telegram_id=claimer_telegram_id,
            result="rate_limited",
        )
        return VerifyResult(
            False, "rate_limited",
            "该账号 24 小时内回群次数过多，请稍后再试。",
        )

    # ===== 全部通过 → 消费 =====

    # 1. 新一次性入群链接
    db_link = await invite_link_service.create_one_time_link(session, bot, application)

    # 2. 旧密钥置 used，记录使用人/时间，cleanup pending
    old_owner = matched.owner_telegram_id
    matched.status = RK_USED
    matched.used_by_telegram_id = claimer_telegram_id
    matched.used_at = datetime.now(timezone.utc)
    matched.cleanup_action = CLEANUP_PENDING
    await session.flush()

    # 3. 链式签发新密钥（绑定新持有人）
    new_record, new_plaintext = await issue_chained_key(
        session,
        application,
        owner_telegram_id=claimer_telegram_id,
        previous_key_id=matched.id,
    )

    # 4. 触发原账号清理（不阻塞主流程）
    group = await session.get(Group, inviter.target_group_id)
    cleanup_summary = "—"
    if group is not None:
        try:
            res = await account_cleanup_service.cleanup_old_account(
                session,
                bot,
                target_chat_telegram_id=group.telegram_chat_id,
                old_owner_telegram_id=old_owner,
            )
            matched.cleanup_action = res.action
            matched.cleanup_old_account_status = res.old_account_status
            matched.cleanup_executed_at = datetime.now(timezone.utc)
            cleanup_summary = res.summary
            await session.flush()
        except Exception:  # noqa: BLE001
            log.exception("recovery_key_cleanup_outer_failed", key_id=matched.id)

    # 5. 写 success attempt
    await recovery_key_repo.record_attempt(
        session, key_hash=matched.key_hash, attempted_by_telegram_id=claimer_telegram_id,
        result="success",
    )

    # 6. 日志频道：🔑 密钥使用
    try:
        await log_channel_service.push_recovery_key_used(
            session, bot,
            application=application,
            old_owner_telegram_id=old_owner,
            new_owner_telegram_id=claimer_telegram_id,
            new_owner_username=claimer_username,
            invite_link_url=db_link.invite_link,
            cleanup_summary=cleanup_summary,
            old_account_status=matched.cleanup_old_account_status or "unknown",
        )
    except Exception:  # noqa: BLE001
        log.exception("log_channel_recovery_key_used_failed", key_id=matched.id)

    log.info(
        "recovery_key_consumed",
        old_owner_telegram_id=old_owner,
        new_owner_telegram_id=claimer_telegram_id,
        application_id=application.id,
        cleanup=matched.cleanup_action,
    )

    return VerifyResult(
        True,
        "success",
        "✅ 密钥校验通过，已为您生成新的一次性入群链接。",
        invite_link_url=db_link.invite_link,
        new_key_plaintext=new_plaintext,
        application_id=application.id,
        inviter_display=inviter.display_name,
        cleanup_summary=cleanup_summary,
        matched_key_id=matched.id,
    )
