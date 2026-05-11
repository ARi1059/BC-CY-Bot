from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base
from bccy_bot.db.models.enums import APP_STATUS_WIZARD


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('wizard', 'pending', 'approved', 'rejected', 'cancelled')",
            name="ck_applications_status",
        ),
        CheckConstraint(
            "reviewed_by_type IS NULL OR reviewed_by_type IN ('inviter', 'admin')",
            name="ck_applications_reviewed_by_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    applicant_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applicant_display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    inviter_id: Mapped[int | None] = mapped_column(ForeignKey("inviters.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=APP_STATUS_WIZARD, nullable=False, index=True
    )
    wizard_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    locked_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
