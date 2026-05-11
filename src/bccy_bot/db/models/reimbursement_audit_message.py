from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base


class ReimbursementAuditMessage(Base):
    """报销审核消息推送记录（与 audit_messages 同构）。"""

    __tablename__ = "reimbursement_audit_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    reimbursement_id: Mapped[int] = mapped_column(
        ForeignKey("reimbursement_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reviewer_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    media_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    text_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    report_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
