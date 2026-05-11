"""audit_service 集成测试：用 FakeBot 隔离 Telegram API。"""

from dataclasses import dataclass, field

import pytest

from bccy_bot.db.models.enums import (
    APP_STATUS_APPROVED,
    APP_STATUS_PENDING,
    APP_STATUS_REJECTED,
    CT_PHOTO,
    CT_TEXT,
    MAT_BOOKING,
    MAT_GESTURE,
    MAT_REPORT,
    REVIEW_MODE_DELEGATED,
    REVIEW_MODE_SELF,
)
from bccy_bot.services import audit_service


# ---------- FakeBot ----------


@dataclass
class _SentMedia:
    chat_id: int
    media: list  # InputMediaPhoto list
    message_ids: list[int] = field(default_factory=list)


@dataclass
class _SentText:
    chat_id: int
    text: str
    reply_markup: object | None
    message_id: int = 0


@dataclass
class _EditedText:
    chat_id: int
    message_id: int
    text: str


@dataclass
class _Message:
    """模拟 telegram.Message 的最小接口。"""
    message_id: int


@dataclass
class _ChatInviteLink:
    invite_link: str
    expire_date: object | None = None


class FakeBot:
    def __init__(self):
        self.sent_media: list[_SentMedia] = []
        self.sent_texts: list[_SentText] = []
        self.edited: list[_EditedText] = []
        self.created_links: list[dict] = []
        self._next_msg_id = 1000

    def _next(self) -> int:
        self._next_msg_id += 1
        return self._next_msg_id

    async def send_media_group(self, chat_id, media):
        msg_ids = [self._next() for _ in media]
        self.sent_media.append(_SentMedia(chat_id=chat_id, media=list(media), message_ids=msg_ids))
        return [_Message(message_id=mid) for mid in msg_ids]

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        msg_id = self._next()
        self.sent_texts.append(_SentText(chat_id=chat_id, text=text, reply_markup=reply_markup, message_id=msg_id))
        return _Message(message_id=msg_id)

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        self.edited.append(_EditedText(chat_id=chat_id, message_id=message_id, text=text))
        return _Message(message_id=message_id)

    async def create_chat_invite_link(
        self, chat_id, member_limit, expire_date, name, creates_join_request
    ):
        self.created_links.append(
            dict(chat_id=chat_id, member_limit=member_limit, expire_date=expire_date, name=name)
        )
        return _ChatInviteLink(invite_link=f"https://t.me/+fake_{name}")


# ---------- Fixtures ----------


@pytest.fixture
def bot():
    return FakeBot()


async def _seed_full_pending(session, *, review_mode=REVIEW_MODE_SELF, inviter_tg_id: int | None = 999):
    """种入一份 pending 申请，含 2 photo + 1 text 材料。"""
    from bccy_bot.db.models.application import Application
    from bccy_bot.db.models.application_material import ApplicationMaterial
    from bccy_bot.db.models.group import Group
    from bccy_bot.db.models.inviter import Inviter
    from datetime import datetime, timezone

    grp = Group(telegram_chat_id=-100123, name="测试群")
    session.add(grp)
    await session.flush()

    inv = Inviter(
        telegram_user_id=inviter_tg_id,
        display_name="张老师",
        group_label="A组",
        target_group_id=grp.id,
        required_materials=[MAT_BOOKING, MAT_GESTURE, MAT_REPORT],
        review_mode=review_mode,
        is_active=True,
    )
    session.add(inv)
    await session.flush()

    app = Application(
        applicant_telegram_id=42,
        applicant_username="apply_user",
        applicant_display_name="申请人",
        inviter_id=inv.id,
        status=APP_STATUS_PENDING,
        wizard_step=0,
        submitted_at=datetime(2026, 5, 12, 14, 23, tzinfo=timezone.utc),
    )
    session.add(app)
    await session.flush()

    for i, (mt, ct, tag) in enumerate([
        (MAT_BOOKING, CT_PHOTO, "booking-file-id"),
        (MAT_GESTURE, CT_PHOTO, "gesture-file-id"),
        (MAT_REPORT, CT_TEXT, "今天出击 5 次成功"),
    ]):
        m = ApplicationMaterial(
            application_id=app.id,
            material_type=mt,
            content_type=ct,
            telegram_file_id=tag if ct == CT_PHOTO else None,
            text_content=tag if ct == CT_TEXT else None,
            original_message_id=100 + i,
        )
        session.add(m)
    await session.flush()
    return app, inv, grp


# ---------- notify_reviewers ----------


@pytest.mark.asyncio
async def test_notify_self_review_sends_double_message(session, bot):
    app, inv, _ = await _seed_full_pending(session)

    await audit_service.notify_reviewers(session, bot, app)

    assert len(bot.sent_media) == 1
    media = bot.sent_media[0]
    assert media.chat_id == inv.telegram_user_id
    assert len(media.media) == 2  # 约课记录 + 上课手势
    # 首图带 caption（出击报告）
    assert media.media[0].caption == "今天出击 5 次成功"
    assert media.media[1].caption is None

    assert len(bot.sent_texts) == 1
    text_msg = bot.sent_texts[0]
    assert text_msg.chat_id == inv.telegram_user_id
    assert f"#A{app.id}" in text_msg.text
    assert "@apply_user" in text_msg.text
    # 报告不应该在第二条消息中重复
    assert "今天出击" not in text_msg.text
    assert text_msg.reply_markup is not None  # 含审核按钮

    # audit_messages 行已落库
    from sqlalchemy import select

    from bccy_bot.db.models.audit_message import AuditMessage
    rows = (await session.execute(select(AuditMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].reviewer_telegram_id == inv.telegram_user_id


@pytest.mark.asyncio
async def test_notify_long_report_downgrades_to_three_messages(session, bot):
    """报告超过 1024 字符 → 三消息（媒体组无 caption + 独立报告 + 按钮）。"""
    app, inv, _ = await _seed_full_pending(session)

    # 把报告改成超长
    from sqlalchemy import select

    from bccy_bot.db.models.application_material import ApplicationMaterial
    long_text = "x" * 1500
    report_mat = (
        await session.execute(
            select(ApplicationMaterial).where(
                ApplicationMaterial.application_id == app.id,
                ApplicationMaterial.material_type == MAT_REPORT,
            )
        )
    ).scalar_one()
    report_mat.text_content = long_text
    await session.flush()

    await audit_service.notify_reviewers(session, bot, app)

    assert len(bot.sent_media) == 1
    assert bot.sent_media[0].media[0].caption is None  # caption 留空

    assert len(bot.sent_texts) == 2  # 独立报告 + 按钮
    assert long_text in bot.sent_texts[0].text  # 第一条是报告
    assert bot.sent_texts[0].reply_markup is None
    assert "#A" in bot.sent_texts[1].text  # 第二条是审核卡片
    assert bot.sent_texts[1].reply_markup is not None


@pytest.mark.asyncio
async def test_notify_delegated_mode_is_skipped_in_m2(session, bot):
    """代审型 M2 阶段不推送（M3 接管）。"""
    app, _, _ = await _seed_full_pending(session, review_mode=REVIEW_MODE_DELEGATED)
    await audit_service.notify_reviewers(session, bot, app)
    assert bot.sent_media == []
    assert bot.sent_texts == []


@pytest.mark.asyncio
async def test_notify_self_review_inviter_without_tg_id_is_skipped(session, bot):
    """自审型 inviter 没有 telegram_user_id 时跳过推送。"""
    app, _, _ = await _seed_full_pending(session, inviter_tg_id=None)
    await audit_service.notify_reviewers(session, bot, app)
    assert bot.sent_texts == []


# ---------- approve_application ----------


@pytest.mark.asyncio
async def test_approve_creates_link_issues_key_notifies(session, bot):
    app, inv, _ = await _seed_full_pending(session)
    await audit_service.notify_reviewers(session, bot, app)
    initial_text_count = len(bot.sent_texts)

    result = await audit_service.approve_application(
        session,
        bot,
        app,
        reviewer_telegram_id=inv.telegram_user_id,
        reviewer_role="inviter",
        reviewer_display="@zhang_laoshi",
    )

    assert app.status == APP_STATUS_APPROVED
    assert result.invite_link_url.startswith("https://t.me/+fake_App-")
    assert result.recovery_key_plaintext is not None
    assert result.recovery_key_plaintext.startswith("BCCY-")

    # 申请人收到链接 + 密钥消息
    applicant_msg = bot.sent_texts[initial_text_count]
    assert applicant_msg.chat_id == 42  # applicant_telegram_id
    assert result.recovery_key_plaintext in applicant_msg.text

    # 审核消息 ② 被编辑为"已通过"
    assert len(bot.edited) == 1
    edited = bot.edited[0]
    assert edited.chat_id == inv.telegram_user_id
    assert "已通过" in edited.text
    assert "@zhang_laoshi" in edited.text

    # 数据库：链接 + 密钥已落库
    from sqlalchemy import select

    from bccy_bot.db.models.invite_link import InviteLink
    from bccy_bot.db.models.recovery_key import RecoveryKey

    links = (await session.execute(select(InviteLink))).scalars().all()
    assert len(links) == 1
    assert links[0].invite_link_name == f"App-{app.id}"

    keys = (await session.execute(select(RecoveryKey))).scalars().all()
    assert len(keys) == 1


@pytest.mark.asyncio
async def test_approve_already_approved_rejected(session, bot):
    app, inv, _ = await _seed_full_pending(session)
    app.status = APP_STATUS_APPROVED
    await session.flush()

    with pytest.raises(audit_service.AuditError):
        await audit_service.approve_application(
            session, bot, app,
            reviewer_telegram_id=999, reviewer_role="inviter", reviewer_display="@x",
        )


# ---------- reject_application ----------


@pytest.mark.asyncio
async def test_reject_with_reason_notifies_applicant(session, bot):
    app, inv, _ = await _seed_full_pending(session)
    await audit_service.notify_reviewers(session, bot, app)
    initial = len(bot.sent_texts)

    await audit_service.reject_application(
        session, bot, app,
        reviewer_telegram_id=inv.telegram_user_id,
        reviewer_role="inviter",
        reason="材料不齐",
        reviewer_display="@x",
    )
    assert app.status == APP_STATUS_REJECTED
    assert app.reject_reason == "材料不齐"

    applicant_msg = bot.sent_texts[initial]
    assert applicant_msg.chat_id == 42
    assert "材料不齐" in applicant_msg.text

    edited = bot.edited[0]
    assert "已拒绝" in edited.text
    assert "材料不齐" in edited.text


@pytest.mark.asyncio
async def test_reject_without_reason(session, bot):
    app, inv, _ = await _seed_full_pending(session)
    await audit_service.notify_reviewers(session, bot, app)

    await audit_service.reject_application(
        session, bot, app,
        reviewer_telegram_id=inv.telegram_user_id,
        reviewer_role="inviter",
        reason=None,
        reviewer_display="@x",
    )
    assert app.status == APP_STATUS_REJECTED
    assert app.reject_reason is None


@pytest.mark.asyncio
async def test_reject_already_processed_rejected(session, bot):
    app, _, _ = await _seed_full_pending(session)
    app.status = APP_STATUS_REJECTED
    await session.flush()

    with pytest.raises(audit_service.AuditError):
        await audit_service.reject_application(
            session, bot, app,
            reviewer_telegram_id=999, reviewer_role="inviter", reason=None,
        )
