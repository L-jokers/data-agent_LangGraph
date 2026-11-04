from sqlalchemy import ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class DimensionInfoMySQL(Base):
    __tablename__ = "dimension_info"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "table_id"],
            ["table_info.version_id", "table_info.id"],
            name="fk_dimension_version_table",
        ),
        ForeignKeyConstraint(
            ["version_id", "column_id"],
            ["column_info.version_id", "column_info.id"],
            name="fk_dimension_version_column",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    table_id: Mapped[str] = mapped_column(String(64), nullable=False)
    column_id: Mapped[str] = mapped_column(String(64), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
