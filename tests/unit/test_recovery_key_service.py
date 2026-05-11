import re

import pytest

from bccy_bot.db.models.enums import APP_STATUS_PENDING, RK_ACTIVE
from bccy_bot.db.models.recovery_key import RecoveryKey
from bccy_bot.services import recovery_key_service


# ---------- 明文生成 ----------


def test_key_format_matches_spec():
    """BCCY-XXXX-XXXX-XXXX-XXXX，4 段 × 4 位，无 0/O/1/I/L。"""
    pattern = re.compile(r"^BCCY-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")
    forbidden = set("01OIL")
    for _ in range(100):
        k = recovery_key_service.generate_key_plaintext()
        assert pattern.match(k), f"bad format: {k}"
        body = k.replace("-", "").replace("BCCY", "")
        assert forbidden.isdisjoint(body), f"forbidden char in {k}"


def test_keys_are_unique_random():
    keys = {recovery_key_service.generate_key_plaintext() for _ in range(500)}
    assert len(keys) == 500  # 极小概率碰撞，500 次足够安全


# ---------- 哈希与验证 ----------


def test_hash_round_trip():
    k = recovery_key_service.generate_key_plaintext()
    h = recovery_key_service.hash_key(k)
    assert h != k
    assert recovery_key_service.verify_key(k, h) is True
    assert recovery_key_service.verify_key("BCCY-XXXX-XXXX-XXXX-XXXX", h) is False


def test_key_prefix_display():
    k = "BCCY-A7K9-X3F2-Q8M4-R5N1"
    assert recovery_key_service.key_prefix_display(k) == "BCCY-A7K9"


# ---------- issue_first_key（DB 集成） ----------


async def _seed_application(session, applicant_id: int = 1):
    from bccy_bot.db.models.application import Application

    app = Application(
        applicant_telegram_id=applicant_id,
        applicant_username="u",
        applicant_display_name="U",
        status=APP_STATUS_PENDING,
        wizard_step=0,
    )
    session.add(app)
    await session.flush()
    return app


@pytest.mark.asyncio
async def test_issue_first_key_creates_active_record(session):
    app = await _seed_application(session)
    result = await recovery_key_service.issue_first_key(session, app)
    assert result is not None
    record, plaintext = result
    assert record.status == RK_ACTIVE
    assert record.application_id == app.id
    assert record.owner_telegram_id == app.applicant_telegram_id
    assert record.original_owner_telegram_id == app.applicant_telegram_id
    assert record.key_prefix == plaintext[:9]
    # 哈希校验
    assert recovery_key_service.verify_key(plaintext, record.key_hash)


@pytest.mark.asyncio
async def test_issue_first_key_is_idempotent(session):
    app = await _seed_application(session)
    first = await recovery_key_service.issue_first_key(session, app)
    assert first is not None

    second = await recovery_key_service.issue_first_key(session, app)
    assert second is None  # 已有 active 密钥，不重复签发


@pytest.mark.asyncio
async def test_issue_after_old_used_creates_new(session):
    from bccy_bot.db.models.enums import RK_USED

    app = await _seed_application(session)
    first = await recovery_key_service.issue_first_key(session, app)
    assert first is not None
    record, _ = first
    record.status = RK_USED
    await session.flush()

    # 旧密钥置为 used 后，可以再签发新的
    second = await recovery_key_service.issue_first_key(session, app)
    assert second is not None
    new_record, _ = second
    assert new_record.id != record.id
