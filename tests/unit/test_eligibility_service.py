"""eligibility_service：成员判定 + 缓存语义。"""

from dataclasses import dataclass

import pytest
from telegram.error import BadRequest

from bccy_bot.repositories import eligibility_chat_repo
from bccy_bot.services import eligibility_service


@dataclass
class _Member:
    status: str


class FakeBot:
    def __init__(self):
        # (chat_id, user_id) → status 或 Exception
        self.member_map: dict[tuple[int, int], object] = {}

    async def get_chat_member(self, chat_id, user_id):
        v = self.member_map.get((chat_id, user_id))
        if v is None:
            raise BadRequest("user not found")
        if isinstance(v, Exception):
            raise v
        return _Member(status=v)


async def _seed_chats(session, ids: list[int]) -> None:
    for cid in ids:
        await eligibility_chat_repo.create(
            session, telegram_chat_id=cid, chat_type="channel", name=f"Chat{cid}"
        )


# ---------- 行为 ----------


@pytest.mark.asyncio
async def test_no_active_chats_returns_not_ok(session):
    bot = FakeBot()
    r = await eligibility_service.check_membership(session, bot, user_id=42)
    assert r.ok is False
    assert r.checked_chats == 0


@pytest.mark.asyncio
async def test_user_in_all_chats_is_ok(session):
    await _seed_chats(session, [-1, -2, -3])
    bot = FakeBot()
    for cid in (-1, -2, -3):
        bot.member_map[(cid, 42)] = "member"
    r = await eligibility_service.check_membership(session, bot, user_id=42)
    assert r.ok is True
    assert r.checked_chats == 3
    assert r.missing_chat_names == []


@pytest.mark.asyncio
async def test_user_missing_one_chat_fails(session):
    await _seed_chats(session, [-10, -20])
    bot = FakeBot()
    bot.member_map[(-10, 42)] = "member"
    bot.member_map[(-20, 42)] = "left"
    r = await eligibility_service.check_membership(session, bot, user_id=42)
    assert r.ok is False
    assert any("Chat-20" in n for n in r.missing_chat_names)


@pytest.mark.asyncio
async def test_user_not_found_treated_as_missing(session):
    await _seed_chats(session, [-30])
    bot = FakeBot()
    # 不设置 member_map → get_chat_member 抛 user not found
    r = await eligibility_service.check_membership(session, bot, user_id=99)
    assert r.ok is False
    assert any("Chat-30" in n for n in r.missing_chat_names)


@pytest.mark.asyncio
async def test_admin_and_creator_count_as_present(session):
    await _seed_chats(session, [-40, -41])
    bot = FakeBot()
    bot.member_map[(-40, 42)] = "administrator"
    bot.member_map[(-41, 42)] = "creator"
    r = await eligibility_service.check_membership(session, bot, user_id=42)
    assert r.ok is True


# ---------- 缓存 ----------


@pytest.mark.asyncio
async def test_success_result_is_cached(session):
    await _seed_chats(session, [-50])
    bot = FakeBot()
    bot.member_map[(-50, 42)] = "member"
    bot_data: dict = {}

    r1 = await eligibility_service.check_membership(
        session, bot, user_id=42, bot_data=bot_data
    )
    assert r1.ok is True

    # 改 bot：把成员变成 left，但缓存仍命中
    bot.member_map[(-50, 42)] = "left"
    r2 = await eligibility_service.check_membership(
        session, bot, user_id=42, bot_data=bot_data
    )
    assert r2.ok is True  # 用了缓存

    # 清缓存后再查 → 真实状态
    eligibility_service.clear_cache_for_user(bot_data, 42)
    r3 = await eligibility_service.check_membership(
        session, bot, user_id=42, bot_data=bot_data
    )
    assert r3.ok is False


@pytest.mark.asyncio
async def test_failure_not_cached(session):
    """失败结果不进缓存：用户中途加群应立即可用。"""
    await _seed_chats(session, [-60])
    bot = FakeBot()
    bot.member_map[(-60, 42)] = "left"
    bot_data: dict = {}

    r1 = await eligibility_service.check_membership(
        session, bot, user_id=42, bot_data=bot_data
    )
    assert r1.ok is False

    # 修复：用户加群了
    bot.member_map[(-60, 42)] = "member"
    r2 = await eligibility_service.check_membership(
        session, bot, user_id=42, bot_data=bot_data
    )
    assert r2.ok is True
