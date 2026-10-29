from dataclasses import dataclass


@dataclass
class DatasetInfo:
    id: str
    table_name: str
    grain: str
    primary_key: str
    time_dimension_id: str
