from dataclasses import asdict

from app.entities.dataset_info import DatasetInfo
from app.models.dataset_info_mysql import DatasetInfoMySQL


class DatasetInfoMapper:
    @staticmethod
    def to_model(entity: DatasetInfo) -> DatasetInfoMySQL:
        return DatasetInfoMySQL(**asdict(entity))
