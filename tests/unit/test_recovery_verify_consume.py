"""verify_and_consume：7 条校验路径 + 成功消费 + 频率限制 + 同 ID 拦截。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from bccy_bot.db.models.application import Application
from bccy_bot.db.models.blacklist import Blacklist
from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    CLEANUP_BAN,
    CLEANUP_SKIP_NOT_IN_GROUP,
    MAT_REPORT,
    REVIEW_MODE_SELF,
    RK_ACTIVE,
    RK_USED,
)
from bccy_bot.db.models.group import Group
from bccy_bot.db.models.inviter import Inviter
from bccy_bot.db.models.recovery_key import RecoveryKey
from bccy_bot.db.models.recovery_key_attempt import RecoveryKeyAttempt
from bccy_bot.repositories import settings_repo
from bccy_bot.services import recovery_key_service
from sqlalchemy import select


# ---------- FakeBot 满足 verify_and_consume 用到的 API ----------


@dataclass
class _MemberStub:
    status: str
    user: object | None = None


class FakeBot:
    def __init__(self):
        self.kicked_users: list[tuple[int, int]] = []
        self.banned_users: list[tuple[int, int]] = []
        self.unbanned_users: list[tuple[int, int]] = []
        self.sent_texts: list[dict] = []
        self.created_links: list[dict] = []
        self.member_lookup: dict[tuple[int, int], _MemberStub] = {}
        self._next = 9000

    async def get_chat_member(self, chat_id, user_id):
        m = self.member_lookup.get((chat_id, user_id))
        if m is None:
            # 默认：原账号已离开群
            return _MemberStub(status="left")
        return m

    async def ban_chat_member(self, chat_id, user_id, **kwargs):
        self.banned_users.append((chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, **kwargs):
        self.unbanned_users.append((chat_id, user_id))

    async def create_chat_invite_link(
        self, chat_id, member_limit, expire_date, name, creates_join_request
    ):
        from dataclasses import dataclass as _dc

        @_dc
        class _CIL:
            invite_link: str
            expire_date: object = None

        self.created_links.append(dict(name=name))
        return _CIL(invite_link=f"https://t.me/+fake_{name}")

    async def send_message(self, chat_id, text, **kwargs):
        self.sent_texts.append(dict(chat_id=chat_id, text=text))
        from dataclasses import dataclass as _dc

        @_dc
        class _Msg:
            message_id: int

        self._next += 1
        return _Msg(message_id=self._next)


# ---------- 数据准备 ----------


async def _seed(session, *, applicant_id: int = 100, original_owner: int | None = None):
    grp = Group(telegram_chat_id=-100888, name="测试群")
    session.add(grp)
    await session.flush()
    inv = Inviter(
        telegram_user_id=200,
        display_name="张老师",
            target_group_id=grp.id,
        required_materials=[MAT_REPORT],
        review_mode=REVIEW_MODE_SELF,
        is_active=True,
    )
    session.add(inv)
    await session.flush()
    app = Application(
        applicant_telegram_id=applicant_id,
        applicant_username="alice",
        inviter_id=inv.id,
        status=APP_STATUS_APPROVED,
        wizard_step=0,
    )
    session.add(app)
    await session.flush()
    return grp, inv, app


async def _issue_key(session, app: Application, owner_id: int | None = None):
    """直接签发一把 active 密钥，返回 (record, plaintext)。"""
    if owner_id is None:
        owner_id = app.applicant_telegram_id
    plaintext = recovery_key_service.generate_key_plaintext()
    record = RecoveryKey(
            application_id=app.id,
        owner_telegram_id=owner_id,
        original_owner_telegram_id=app.applicant_telegram_id,
        key_hash=recovery_key_service.hash_key(plaintext),
        key_prefix=recovery_key_service.key_prefix_display(plaintext),
        status=RK_ACTIVE,
    )
    session.add(record)
    await session.flush()
    return record, plaintext


# ---------- Rule 1: format ----------


@pytest.mark.asyncio
async def test_invalid_format_rejected(session):
    await _seed(session)
    bot = FakeBot()
    r = await recovery_key_service.verify_and_consume(
        session, bot, key_plaintext="abc", claimer_telegram_id=999,
    )
    assert r.success is False
    assert r.reason_code == "invalid_format"


# ---------- Rule 2: not found ----------


@pytest.mark.asyncio
async def test_unknown_key_returns_unified_message(session):
    await _seed(session)
    fake = recovery_key_service.generate_key_plaintext()
    bot = FakeBot()
    r = await recovery_key_service.verify_and_consume(
        session, bot, key_plaintext=fake, claimer_telegram_id=999,
    )
    assert r.success is False
    assert r.reason_code == "not_found"
    # 防探测：消息统一
    assert "无效" in r.user_message


# ---------- Rule 3: same ID ----------


@pytest.mark.asyncio
async def test_same_id_rejected_core_protection(session):
    _, _, app = await _seed(session)
    _, plaintext = await _issue_key(session, app)
    bot = FakeBot()

    r = await recovery_key_service.verify_and_consume(
        session, bot,
        key_plaintext=plaintext,
        claimer_telegram_id=app.applicant_telegram_id,  # 与原持有人相同
    )
    assert r.success is False
    assert r.reason_code == "same_id"


# ---------- Rule 4: blacklist ----------


@pytest.mark.asyncio
async def test_blacklisted_claimer_rejected(session):
    _, _, app = await _seed(session)
    _, plaintext = await _issue_key(session, app)
    session.add(Blacklist(telegram_user_id=999, reason="bad guy", added_by=None))
    await session.flush()

    bot = FakeBot()
    r = await recovery_key_service.verify_and_consume(
        session, bot, key_plaintext=plaintext, claimer_telegram_id=999,
    )
    assert r.success is False
    assert r.reason_code == "blacklisted"


# ---------- Rule 5: inviter inactive ----------


@pytest.mark.asyncio
async def test_inactive_inviter_rejected(session):
    _, inv, app = await _seed(session)
    _, plaintext = await _issue_key(session, app)
    inv.is_active = False
    await session.flush()

    bot = FakeBot()
    r = await recovery_key_service.verify_and_consume(
        session, bot, key_plaintext=plaintext, claimer_telegram_id=999,
    )
    assert r.success is False
    assert r.reason_code == "inviter_inactive"


# ---------- Rule 6: per-key fail lock ----------


@pytest.mark.asyncio
async def test_per_key_fail_lock_after_5_failures(session):
    _, _, app = await _seed(session)
    record, plaintext = await _issue_key(session, app)
    # 预先注入 5 次失败 attempts
    now = datetime.now(timezone.utc)
    for _ in range(5):
        session.add(
            RecoveryKeyAttempt(
                key_hash_attempted=record.key_hash,
                attempted_by_telegram_id=999,
                result="not_found",
                attempted_at=now - timedelta(minutes=5),
            )
        )
    await session.flush()

    bot = FakeBot()
    r = await recovery_key_service.verify_and_consume(
        session, bot, key_plaintext=plaintext, claimer_telegram_id=999,
    )
    assert r.success is False
    assert r.reason_code == "rate_limited"


# ---------- Rule 7: per-claimer success lock ----------


@pytest.mark.asyncio
async def test_per_claimer_success_lock_after_3_uses(session):
    _, _, app = await _seed(session)
    _, plaintext = await _issue_key(session, app)
    now = datetime.now(timezone.utc)
    for _ in range(3):
        session.add(
            RecoveryKeyAttempt(
                key_hash_attempted=None,
                attempted_by_telegram_id=999,
                result="success",
                attempted_at=now - timedelta(hours=1),
            )
        )
    await session.flush()

    bot = FakeBot()
    r = await recovery_key_service.verify_and_consume(
        session, bot, key_plaintext=plaintext, claimer_telegram_id=999,
    )
    assert r.success is False
    assert r.reason_code == "rate_limited"


# ---------- 全部通过：成功消费 ----------


@pytest.mark.asyncio
async def test_full_success_flow_consumes_key_and_issues_new(session):
    _, _, app = await _seed(session)
    record, plaintext = await _issue_key(session, app)
    old_key_id = record.id

    bot = FakeBot()
    r = await recovery_key_service.verify_and_consume(
        session, bot, key_plaintext=plaintext, claimer_telegram_id=999, claimer_username="newuser",
    )
    assert r.success is True
    assert r.reason_code == "success"
    assert r.invite_link_url is not None
    assert r.new_key_plaintext is not None
    assert r.new_key_plaintext != plaintext  # 新签发

    # 旧密钥 used + 标记使用者
    await session.refresh(record)
    assert record.status == RK_USED
    assert record.used_by_telegram_id == 999
    assert record.used_at is not None
    # 清理动作已记录（这里 mock 中原账号未在群 → skip_not_in_group）
    assert record.cleanup_action == CLEANUP_SKIP_NOT_IN_GROUP

    # 新密钥已落库（owner = 新 ID，链式 previous_key_id）
    new_keys = (
        await session.execute(
            select(RecoveryKey).where(RecoveryKey.status == RK_ACTIVE)
        )
    ).scalars().all()
    assert len(new_keys) == 1
    assert new_keys[0].owner_telegram_id == 999
    assert new_keys[0].previous_key_id == old_key_id

    # success attempt 已写
    suc = (
        await session.execute(
            select(RecoveryKeyAttempt).where(RecoveryKeyAttempt.result == "success")
        )
    ).scalars().all()
    assert len(suc) == 1


@pytest.mark.asyncio
async def test_success_flow_bans_normal_old_account_in_group(session):
    """v1.0.0-beta.3：正常账号 + 在群内的清理策略改为永久封禁（不再 unban）。"""
    grp, _, app = await _seed(session)
    _, plaintext = await _issue_key(session, app)
    original_owner_id = app.applicant_telegram_id  # consume 后会被覆盖为 claimer

    bot = FakeBot()
    bot.member_lookup[(grp.telegram_chat_id, original_owner_id)] = _MemberStub(
        status="member",
        user=type("U", (), {"first_name": "Alice", "last_name": None, "username": "alice"}),
    )

    r = await recovery_key_service.verify_and_consume(
        session, bot, key_plaintext=plaintext, claimer_telegram_id=999,
    )
    assert r.success is True
    assert bot.banned_users == [(grp.telegram_chat_id, original_owner_id)]
    # 不再 unban —— 永久封禁
    assert bot.unbanned_users == []
    # 申请记录的当前持有人已迁移到新账号
    assert app.applicant_telegram_id == 999


@pytest.mark.asyncio
async def test_success_flow_bans_deactivated_old_account(session):
    grp, _, app = await _seed(session)
    _, plaintext = await _issue_key(session, app)
    original_owner_id = app.applicant_telegram_id

    bot = FakeBot()
    bot.member_lookup[(grp.telegram_chat_id, original_owner_id)] = _MemberStub(
        status="member",
        user=type("U", (), {"first_name": "Deleted Account", "last_name": None, "username": None}),
    )

    r = await recovery_key_service.verify_and_consume(
        session, bot, key_plaintext=plaintext, claimer_telegram_id=999,
    )
    assert r.success is True

    # 永久封禁（banned 但未 unban）
    assert bot.banned_users == [(grp.telegram_chat_id, original_owner_id)]
    assert bot.unbanned_users == []

    # 本地黑名单已写入
    bl = (
        await session.execute(
            select(Blacklist).where(Blacklist.telegram_user_id == original_owner_id)
        )
    ).scalar_one_or_none()
    assert bl is not None
    assert "注销" in (bl.reason or "")
    # 申请记录的当前持有人已迁移到新账号
    assert app.applicant_telegram_id == 999
