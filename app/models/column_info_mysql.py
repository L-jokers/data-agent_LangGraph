from sqlalchemy import ForeignKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class ColumnInfoMySQL(Base):
    __tablename__ = "column_info"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "table_id"],
            ["table_info.version_id", "table_info.id"],
            name="fk_column_info_version_table",
        ),
        ForeignKeyConstraint(
            ["version_id"], ["semantic_model_version.version_id"],
            name="fk_column_info_version",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="列编号")
    name: Mapped[str | None] = mapped_column(String(128), comment="列名称")
    type: Mapped[str | None] = mapped_column(String(64), comment="数据类型")
    role: Mapped[str | None] = mapped_column(
        String(32), comment="列类型(primary_key,foreign_key,measure,dimension)"
    )
    examples: Mapped[dict | list | None] = mapped_column(JSON, comment="数据示例")
    description: Mapped[str | None] = mapped_column(Text, comment="列描述")
    alias: Mapped[dict | list | None] = mapped_column(JSON, comment="列别名")
    table_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="所属表编号")
