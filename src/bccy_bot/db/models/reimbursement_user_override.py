from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base


class ReimbursementUserOverride(Base):
    """单用户冷却天数覆盖（[REQ §8.5.6]）。"""

    __tablename__ = "reimbursement_user_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    cooldown_days: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
