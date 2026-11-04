from sqlalchemy import ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DatasetInfoMySQL(Base):
    __tablename__ = "dataset"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "table_name"],
            ["table_info.version_id", "table_info.id"],
            name="fk_dataset_version_table",
        ),
        ForeignKeyConstraint(
            ["version_id"], ["semantic_model_version.version_id"],
            name="fk_dataset_version",
        ),
        ForeignKeyConstraint(
            ["version_id", "time_dimension_id"],
            ["time_dimension.version_id", "time_dimension.id"],
            name="fk_dataset_version_time_dimension",
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    grain: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_key: Mapped[str] = mapped_column(String(128), nullable=False)
    time_dimension_id: Mapped[str] = mapped_column(String(64), nullable=False)
