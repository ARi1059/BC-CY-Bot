"""报销老师（[v1.0.0-beta.3] 新增）。与邀请人无关，纯粹为报销系统服务。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base
from bccy_bot.db.models.enums import REI_TIER_DEFAULT_CENTS


class ReimburseTeacher(Base):
    __tablename__ = "reimburse_teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    group_label: Mapped[str] = mapped_column(String(64), nullable=False)
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
