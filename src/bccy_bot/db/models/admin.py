from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from bccy_bot.db.base import Base


class Admin(Base):
    __tablename__ = "admins"
    __table_args__ = (
        CheckConstraint("role IN ('super', 'sub')", name="ck_admins_role"),
        # 全表至多 1 行 role='super'（部分唯一索引，PG/SQLite 均支持）
        Index(
            "uq_one_super_admin",
            "role",
            unique=True,
            postgresql_where=text("role = 'super'"),
            sqlite_where=text("role = 'super'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
