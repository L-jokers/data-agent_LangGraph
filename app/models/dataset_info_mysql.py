from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


class DatasetInfoMySQL(Base):
    __tablename__ = "dataset"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    grain: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_key: Mapped[str] = mapped_column(String(128), nullable=False)
    time_dimension_id: Mapped[str] = mapped_column(String(64), nullable=False)
