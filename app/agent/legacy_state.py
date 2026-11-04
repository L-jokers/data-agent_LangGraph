"""Deprecated compatibility types for the removed pre-T9 recall nodes.

These types are not part of the formal LangGraph state and are not used by
the production query path.
"""

from typing import TypedDict


class ColumnInfoState(TypedDict):
    name: str
    type: str
    role: str
    examples: list
    description: str
    alias: list[str]


class TableInfoState(TypedDict):
    name: str
    role: str
    description: str
    columns: list[ColumnInfoState]


class MetricInfoState(TypedDict):
    name: str
    description: str
    relevant_columns: list[str]
    alias: list[str]
