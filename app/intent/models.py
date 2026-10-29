from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class QueryIntentStatus(StrEnum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"


class QueryIntentParseError(ValueError):
    pass


@dataclass
class TimeIntent:
    expression: str
    kind: str = "relative"
    year: int | None = None
    month: int | None = None
    day: int | None = None
    start: str | None = None
    end: str | None = None


@dataclass
class QueryIntent:
    status: QueryIntentStatus
    metrics: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    filters: list[dict[str, Any]] = field(default_factory=list)
    time: TimeIntent | None = None
    group_by: list[str] = field(default_factory=list)
    order_by: list[dict[str, str]] = field(default_factory=list)
    limit: int | None = None
    message: str | None = None
    missing: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: Any) -> "QueryIntent":
        if not isinstance(payload, dict):
            raise QueryIntentParseError("结构化意图必须是JSON对象")

        raw_status = payload.get("status", QueryIntentStatus.READY)
        try:
            status = QueryIntentStatus(raw_status)
        except ValueError as exc:
            raise QueryIntentParseError(f"不支持的意图状态: {raw_status}") from exc

        time_payload = payload.get("time")
        time_intent = None
        if time_payload is not None:
            if not isinstance(time_payload, dict) or not time_payload.get("expression"):
                raise QueryIntentParseError("time必须包含expression")
            time_intent = TimeIntent(**{
                key: value
                for key, value in time_payload.items()
                if key in {"expression", "kind", "year", "month", "day", "start", "end"}
            })

        limit = payload.get("limit")
        if limit is not None and (not isinstance(limit, int) or limit <= 0):
            raise QueryIntentParseError("limit必须是正整数")

        return cls(
            status=status,
            metrics=_string_list(payload.get("metrics", []), "metrics"),
            dimensions=_string_list(payload.get("dimensions", []), "dimensions"),
            filters=_dict_list(payload.get("filters", []), "filters"),
            time=time_intent,
            group_by=_string_list(payload.get("group_by", []), "group_by"),
            order_by=_dict_list(payload.get("order_by", []), "order_by"),
            limit=limit,
            message=payload.get("message"),
            missing=_string_list(payload.get("missing", []), "missing"),
        )


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise QueryIntentParseError(f"{field_name}必须是字符串数组")
    return value


def _dict_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise QueryIntentParseError(f"{field_name}必须是对象数组")
    return value
