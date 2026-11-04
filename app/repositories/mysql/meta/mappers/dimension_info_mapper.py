from dataclasses import asdict

from app.entities.dimension_info import DimensionInfo
from app.models.dimension_info_mysql import DimensionInfoMySQL


class DimensionInfoMapper:
    @staticmethod
    def to_entity(model: DimensionInfoMySQL) -> DimensionInfo:
        return DimensionInfo(
            id=model.id,
            name=model.name,
            table_id=model.table_id,
            column_id=model.column_id,
            aliases=model.aliases or [],
            version_id=model.version_id,
        )

    @staticmethod
    def to_model(entity: DimensionInfo) -> DimensionInfoMySQL:
        return DimensionInfoMySQL(**asdict(entity))
