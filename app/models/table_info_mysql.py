from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TableInfoMySQL(Base):
    __tablename__ = "table_info"
    __table_args__ = (
        UniqueConstraint("version_id", "name", name="uq_table_info_version_name"),
    )

    version_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("semantic_model_version.version_id"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="表编号")
    name: Mapped[str | None] = mapped_column(String(128), comment="表名称")
    role: Mapped[str | None] = mapped_column(String(32), comment="表类型(fact/dim)")
    description: Mapped[str | None] = mapped_column(Text, comment="表描述")
