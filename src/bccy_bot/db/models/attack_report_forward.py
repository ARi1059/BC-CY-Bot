from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base


class AttackReportForward(Base):
    __tablename__ = "attack_report_forwards"
    __table_args__ = (
        CheckConstraint(
            "status IN ('sent', 'failed', 'skipped_no_report', 'skipped_no_channel')",
            name="ck_arf_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), index=True, nullable=False
    )
    # 写入时快照：即使全局频道配置后续变更，旧记录仍可回溯当时转发到的频道
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    forwarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
