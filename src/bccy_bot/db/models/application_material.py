from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base


class ApplicationMaterial(Base):
    __tablename__ = "application_materials"
    __table_args__ = (
        CheckConstraint(
            "material_type IN ('约课记录', '上课手势', '出击报告')",
            name="ck_app_materials_type",
        ),
        CheckConstraint("content_type IN ('photo', 'text')", name="ck_app_materials_content_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    material_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    telegram_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 用户在私聊中提交该材料的原始 message_id（出击报告 forwardMessage 必备）
    original_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_group_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
