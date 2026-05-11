from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base


class RecoveryKeyAttempt(Base):
    __tablename__ = "recovery_key_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash_attempted: Mapped[str | None] = mapped_column(String(256), nullable=True)
    attempted_by_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
