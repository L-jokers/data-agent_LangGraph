from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class TimeDimensionInfoMySQL(Base):
    __tablename__ = "time_dimension"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    year_field: Mapped[str] = mapped_column(String(128), nullable=False)
    quarter_field: Mapped[str] = mapped_column(String(128), nullable=False)
    month_field: Mapped[str] = mapped_column(String(128), nullable=False)
    day_field: Mapped[str] = mapped_column(String(128), nullable=False)
    date_key_field: Mapped[str] = mapped_column(String(128), nullable=False)
    supported_grains: Mapped[list] = mapped_column(JSON, nullable=False)
    month_filter_requires_year: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
