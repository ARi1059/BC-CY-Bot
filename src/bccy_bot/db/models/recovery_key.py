from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base
from bccy_bot.db.models.enums import RK_ACTIVE


class RecoveryKey(Base):
    __tablename__ = "recovery_keys"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'used', 'revoked', 'reset')",
            name="ck_recovery_keys_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True, nullable=False)
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    original_owner_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=RK_ACTIVE, nullable=False, index=True)
    used_by_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    previous_key_id: Mapped[int | None] = mapped_column(ForeignKey("recovery_keys.id"), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cleanup_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cleanup_old_account_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cleanup_executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
