from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base
from bccy_bot.db.models.enums import REI_STATUS_WIZARD


class ReimbursementRequest(Base):
    """报销请求主表（[REQ §8.5.10]）。v1.0.0-beta.3 起与入群审核解耦：仅引用所选老师。"""

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
    # 报销老师；ON DELETE SET NULL 让历史记录在老师被删后仍可读
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("reimburse_teachers.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # 老师 username 在选定瞬间的快照，删老师后仍能展示给审核者/申请人
    teacher_username_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
