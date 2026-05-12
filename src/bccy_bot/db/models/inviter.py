from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base
from bccy_bot.db.models.enums import REI_TIER_DEFAULT_CENTS, REVIEW_MODE_SELF


class Inviter(Base):
    __tablename__ = "inviters"
    __table_args__ = (
        CheckConstraint(
            "review_mode IN ('self', 'admin_delegated')", name="ck_inviters_review_mode"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    group_label: Mapped[str] = mapped_column(String(64))
    target_group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    required_materials: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    review_mode: Mapped[str] = mapped_column(String(32), default=REVIEW_MODE_SELF, nullable=False)
    # 该邀请人引荐的申请人的报销金额（分）。三档其一：10000/15000/20000。
    reimbursement_tier_cents: Mapped[int] = mapped_column(
        Integer,
        default=REI_TIER_DEFAULT_CENTS,
        server_default=str(REI_TIER_DEFAULT_CENTS),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
