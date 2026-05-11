from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base
from bccy_bot.db.models.enums import REI_STATUS_WIZARD


class ReimbursementRequest(Base):
    """报销请求主表（[REQ §8.5.10]）。"""

    __tablename__ = "reimbursement_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('wizard', 'pending', 'approved', 'rejected', 'cancelled', 'paid')",
            name="ck_rei_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    applicant_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applicant_display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # 入群审核通过的那条申请；用于回溯申请人首次入群证据
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default=REI_STATUS_WIZARD, nullable=False, index=True
    )
    wizard_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 申请时刻的固定金额快照（分），后续设置变动不影响历史记录
    amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 口令红包原文：敏感数据，仅审核者与申请人可见
    alipay_code_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
