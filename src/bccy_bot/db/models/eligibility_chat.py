from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base


class EligibilityChat(Base):
    """报销资格校验：申请人必须是所有 is_active=True 行的成员（[REQ §8.5.7]）。"""

    __tablename__ = "eligibility_chats"
    __table_args__ = (
        CheckConstraint(
            "chat_type IN ('group', 'supergroup', 'channel')",
            name="ck_elig_chat_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    chat_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
