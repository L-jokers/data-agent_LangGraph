from sqlalchemy import String, Text
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MetricInfoMySQL(Base):
    __tablename__ = "metric_info"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="指标编码"
    )
    name: Mapped[str | None] = mapped_column(
        String(128),
        comment="指标名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        comment="指标描述"
    )
    relevant_columns: Mapped[dict | list | None] = mapped_column(
        JSON,
        comment="关联字段"
    )
    alias: Mapped[dict | list | None] = mapped_column(
        JSON,
        comment="指标别名"
    )
    metric_type: Mapped[str | None] = mapped_column(
        String(32),
        comment="指标类型"
    )
    expression: Mapped[str | None] = mapped_column(
        Text,
        comment="指标表达式"
    )
    numerator: Mapped[str | None] = mapped_column(
        String(64),
        comment="比例指标分子"
    )
    denominator: Mapped[str | None] = mapped_column(
        String(64),
        comment="比例指标分母"
    )
    base_dataset: Mapped[str | None] = mapped_column(
        String(64),
        comment="基础数据集"
    )
    status: Mapped[str | None] = mapped_column(
        String(32),
        comment="指标状态"
    )
