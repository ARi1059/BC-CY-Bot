"""回群密钥的生成、哈希与签发。完整使用/验证流程在 M8 实现。"""

import secrets

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.enums import RK_ACTIVE
from bccy_bot.db.models.recovery_key import RecoveryKey

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
