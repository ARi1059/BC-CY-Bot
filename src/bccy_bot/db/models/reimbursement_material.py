from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base


class ReimbursementMaterial(Base):
    """报销材料（与申请材料同构）。"""

    __tablename__ = "reimbursement_materials"
    __table_args__ = (
        CheckConstraint(
            "material_type IN ('约课记录', '上课手势', '出击报告')",
            name="ck_rei_mat_type",
        ),
        CheckConstraint("content_type IN ('photo', 'text')", name="ck_rei_mat_content_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reimbursement_id: Mapped[int] = mapped_column(
        ForeignKey("reimbursement_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    material_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    telegram_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_group_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
