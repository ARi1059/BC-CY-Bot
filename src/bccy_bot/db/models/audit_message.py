from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base


class AuditMessage(Base):
    """
    审核消息推送记录。

    每发起一次审核通知（双消息）即写一行：
    - 自审型：仅一行（reviewer = inviter.telegram_user_id）
    - 代审型：每位管理员一行（M3 接管）

    通过/拒绝时根据本表回查 message_id 来编辑原消息。
    """

    __tablename__ = "audit_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reviewer_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    media_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    text_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 长报告降级三消息时记录中间的独立报告消息 ID
    report_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
