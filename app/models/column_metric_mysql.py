from sqlalchemy import ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ColumnMetricMySQL(Base):
    __tablename__ = "column_metric"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "column_id"],
            ["column_info.version_id", "column_info.id"],
            name="fk_column_metric_version_column",
        ),
        ForeignKeyConstraint(
            ["version_id", "metric_id"],
            ["metric_info.version_id", "metric_info.id"],
            name="fk_column_metric_version_metric",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    column_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="列编号")
    metric_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="指标编号")
