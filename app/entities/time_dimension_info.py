from dataclasses import dataclass


@dataclass
class TimeDimensionInfo:
    id: str
    table_name: str
    year_field: str
    quarter_field: str
    month_field: str
    day_field: str
    date_key_field: str
    supported_grains: list[str]
    month_filter_requires_year: bool
