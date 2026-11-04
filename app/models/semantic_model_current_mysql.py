from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SemanticModelCurrentMySQL(Base):
    __tablename__ = "semantic_model_current"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_semantic_model_current_singleton"),
    )

    singleton_id: Mapped[int] = mapped_column(primary_key=True, default=1)
    version_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("semantic_model_version.version_id"), nullable=True
    )
