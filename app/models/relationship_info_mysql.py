from sqlalchemy import Boolean, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RelationshipInfoMySQL(Base):
    __tablename__ = "relationship"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id"], ["semantic_model_version.version_id"],
            name="fk_relationship_version",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    cardinality: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
