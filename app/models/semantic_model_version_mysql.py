from datetime import datetime

from sqlalchemy import CheckConstraint, Computed, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SemanticModelVersionMySQL(Base):
    __tablename__ = "semantic_model_version"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_semantic_model_version_status",
        ),
        UniqueConstraint("active_version_guard", name="uq_semantic_model_one_active"),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    description: Mapped[str | None] = mapped_column(Text)
    active_version_guard: Mapped[int | None] = mapped_column(
        Computed("CASE WHEN status = 'active' THEN 1 ELSE NULL END", persisted=True)
    )
