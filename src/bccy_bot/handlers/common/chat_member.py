"""chat_member 事件 handler：监听用户实际入群。"""

import structlog
from telegram import ChatMember, Update
from telegram.ext import ContextTypes

from bccy_bot.services import link_tracking_service
from bccy_bot.utils.session import session_scope

log = structlog.get_logger()

_PRESENT_STATUSES = (
    ChatMember.MEMBER,
    ChatMember.ADMINISTRATOR,
    ChatMember.OWNER,
    ChatMember.RESTRICTED,
)
_ABSENT_STATUSES = (ChatMember.LEFT, ChatMember.BANNED)

_OUR_LINK_PREFIX = "App-"


async def on_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    监听 chat_member 更新，仅在用户"刚刚通过我们签发的邀请链接入群"时记录。

    判定条件：
    - new_chat_member.status 表示"在群中"（member/administrator/owner/restricted）
    - old_chat_member.status 表示"不在群中"（left/kicked/banned；restricted 不算）
    - invite_link 非空且 name 以 'App-' 开头
    """
    cm = update.chat_member
    if cm is None:
        return

    old_status = cm.old_chat_member.status if cm.old_chat_member else None
    new_status = cm.new_chat_member.status if cm.new_chat_member else None

    if new_status not in _PRESENT_STATUSES:
        return  # 不是"加入"事件（离开/被踢等）
    if old_status not in _ABSENT_STATUSES:
        return  # 已在群中（角色变更等），非首次加入

    invite_link = cm.invite_link
    if invite_link is None or invite_link.name is None:
        return  # 用户没通过链接加入（公开群、被拉入等）
    if not invite_link.name.startswith(_OUR_LINK_PREFIX):
        return  # 非本 Bot 签发的链接

    joined_user = cm.new_chat_member.user
    chat = cm.chat

    log.info(
        "chat_member_joined",
        link_name=invite_link.name,
        joined_user_id=joined_user.id,
        joined_username=joined_user.username,
        chat_id=chat.id,
    )

    async with session_scope(context) as session:
        await link_tracking_service.on_member_joined(
            session,
            invite_link_name=invite_link.name,
            joined_user_id=joined_user.id,
            chat_telegram_id=chat.id,
            bot=context.bot,
            joined_username=joined_user.username,
        )
