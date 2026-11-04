from sqlalchemy import ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MetricDependencyMySQL(Base):
    __tablename__ = "metric_dependency"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "metric_id"],
            ["metric_info.version_id", "metric_info.id"],
            name="fk_metric_dependency_version_metric",
        ),
        ForeignKeyConstraint(
            ["version_id", "depends_on_metric_id"],
            ["metric_info.version_id", "metric_info.id"],
            name="fk_metric_dependency_version_target",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depends_on_metric_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dependency_order: Mapped[int] = mapped_column(primary_key=True, default=0)
