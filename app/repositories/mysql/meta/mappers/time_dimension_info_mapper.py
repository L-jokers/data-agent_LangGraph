from dataclasses import asdict

from app.entities.time_dimension_info import TimeDimensionInfo
from app.models.time_dimension_info_mysql import TimeDimensionInfoMySQL


class TimeDimensionInfoMapper:
    @staticmethod
    def to_model(entity: TimeDimensionInfo) -> TimeDimensionInfoMySQL:
        return TimeDimensionInfoMySQL(**asdict(entity))
