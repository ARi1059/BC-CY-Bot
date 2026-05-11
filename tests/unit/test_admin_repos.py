"""M5 数据层：group / inviter / blacklist / admin 仓库的关键路径测试。"""

import pytest

from bccy_bot.db.models.enums import (
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REVIEW_MODE_SELF,
    ROLE_SUB,
    ROLE_SUPER,
)
from bccy_bot.repositories import (
    admin_repo,
    blacklist_repo,
    group_repo,
    inviter_repo,
)


# ---------- group_repo ----------


@pytest.mark.asyncio
async def test_group_create_and_list(session):
    g = await group_repo.create(session, telegram_chat_id=-100, name="g1")
    assert g.is_active is True
    assert (await group_repo.list_all(session))[0].id == g.id


@pytest.mark.asyncio
async def test_group_deactivate_filters_from_active_list(session):
    g = await group_repo.create(session, telegram_chat_id=-101, name="g2")
    await group_repo.deactivate(session, g)
    assert g.is_active is False
    actives = await group_repo.list_active(session)
    assert g not in actives


@pytest.mark.asyncio
async def test_group_find_by_chat_id(session):
    await group_repo.create(session, telegram_chat_id=-200, name="x")
    found = await group_repo.find_by_telegram_chat_id(session, -200)
    assert found is not None and found.name == "x"
    assert await group_repo.find_by_telegram_chat_id(session, 1) is None


# ---------- inviter_repo ----------


@pytest.mark.asyncio
async def test_inviter_create_and_toggle(session):
    g = await group_repo.create(session, telegram_chat_id=-300, name="g")
    inv = await inviter_repo.create(
        session,
        telegram_user_id=111,
        display_name="张老师",
        group_label="A组",
        target_group_id=g.id,
        required_materials=[MAT_BOOKING, MAT_GESTURE, MAT_REPORT],
        review_mode=REVIEW_MODE_SELF,
    )
    assert inv.is_active is True
    await inviter_repo.toggle_active(session, inv)
    assert inv.is_active is False
    await inviter_repo.toggle_active(session, inv)
    assert inv.is_active is True


@pytest.mark.asyncio
async def test_inviter_delete(session):
    g = await group_repo.create(session, telegram_chat_id=-301, name="g")
    inv = await inviter_repo.create(
        session,
        telegram_user_id=222,
        display_name="李老师",
        group_label="B组",
        target_group_id=g.id,
        required_materials=[MAT_REPORT],
        review_mode=REVIEW_MODE_SELF,
    )
    inv_id = inv.id
    await inviter_repo.delete(session, inv)
    assert await inviter_repo.get_by_id(session, inv_id) is None


# ---------- blacklist_repo ----------


@pytest.mark.asyncio
async def test_blacklist_add_check_remove(session):
    assert await blacklist_repo.is_blacklisted(session, 999) is False
    bl = await blacklist_repo.add(session, telegram_user_id=999, reason="test", added_by=None)
    assert await blacklist_repo.is_blacklisted(session, 999) is True

    found = await blacklist_repo.find_by_telegram_user_id(session, 999)
    assert found is not None and found.id == bl.id

    await blacklist_repo.remove(session, bl)
    assert await blacklist_repo.is_blacklisted(session, 999) is False


# ---------- admin_repo: list / add / remove / transfer ----------


@pytest.mark.asyncio
async def test_admin_list_includes_all_roles(session):
    await admin_repo.ensure_initial_super_admin(session, 100)
    await admin_repo.add_sub_admin(session, telegram_user_id=200, display_name=None, added_by=None)
    admins = await admin_repo.list_all(session)
    assert len(admins) == 2
    roles = {a.role for a in admins}
    assert roles == {ROLE_SUPER, ROLE_SUB}


@pytest.mark.asyncio
async def test_admin_transfer_super_swaps_roles(session):
    await admin_repo.ensure_initial_super_admin(session, 100)
    new = await admin_repo.add_sub_admin(session, telegram_user_id=200, display_name=None, added_by=None)
    current = await admin_repo.get_super_admin(session)
    assert current is not None and current.telegram_user_id == 100

    await admin_repo.transfer_super_admin(
        session, new_super=new, current_super=current, by_telegram_id=100
    )
    await session.refresh(current)
    await session.refresh(new)
    assert current.role == ROLE_SUB
    assert new.role == ROLE_SUPER


@pytest.mark.asyncio
async def test_admin_remove_sub_works_but_not_super(session):
    await admin_repo.ensure_initial_super_admin(session, 100)
    sub = await admin_repo.add_sub_admin(session, telegram_user_id=200, display_name=None, added_by=None)
    await admin_repo.remove_sub_admin(session, sub, by_super_telegram_id=100)
    admins = await admin_repo.list_all(session)
    assert len(admins) == 1 and admins[0].role == ROLE_SUPER

    # 不能用 remove_sub_admin 删除 super
    current = admins[0]
    with pytest.raises(ValueError):
        await admin_repo.remove_sub_admin(session, current, by_super_telegram_id=100)
