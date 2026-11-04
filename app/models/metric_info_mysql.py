from sqlalchemy import ForeignKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class MetricInfoMySQL(Base):
    __tablename__ = "metric_info"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "base_dataset"],
            ["dataset.version_id", "dataset.id"],
            name="fk_metric_version_dataset",
        ),
        ForeignKeyConstraint(
            ["version_id"], ["semantic_model_version.version_id"],
            name="fk_metric_version",
        ),
        ForeignKeyConstraint(
            ["version_id", "numerator"],
            ["metric_info.version_id", "metric_info.id"],
            name="fk_metric_version_numerator",
        ),
        ForeignKeyConstraint(
            ["version_id", "denominator"],
            ["metric_info.version_id", "metric_info.id"],
            name="fk_metric_version_denominator",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="指标编码")
    name: Mapped[str | None] = mapped_column(String(128), comment="指标名称")
    description: Mapped[str | None] = mapped_column(Text, comment="指标描述")
    relevant_columns: Mapped[dict | list | None] = mapped_column(JSON, comment="关联的列")
    alias: Mapped[dict | list | None] = mapped_column(JSON, comment="指标别名")
    metric_type: Mapped[str | None] = mapped_column(String(32), comment="指标类型")
    expression: Mapped[str | None] = mapped_column(Text, comment="指标表达式")
    numerator: Mapped[str | None] = mapped_column(String(64), comment="比例指标分子")
    denominator: Mapped[str | None] = mapped_column(String(64), comment="比例指标分母")
    base_dataset: Mapped[str | None] = mapped_column(String(64), comment="基础数据集")
    status: Mapped[str | None] = mapped_column(String(32), comment="指标状态")
    grain: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="统计粒度")
    period: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="统计周期")
    business_scope: Mapped[str | None] = mapped_column(Text, nullable=True, comment="业务限定")
    aggregation: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="聚合方式")
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="计算阶段")
    allowed_dimensions: Mapped[dict | list | None] = mapped_column(JSON, nullable=True, comment="允许维度")
    expression_ast: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="结构化表达式树")
