from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class QueryIntentStatus(StrEnum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"


class QueryIntentParseError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_SCHEMA", status: QueryIntentStatus = QueryIntentStatus.UNSUPPORTED):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class TimeIntent:
    expression: str
    kind: str = "relative"
    year: int | None = None
    month: int | None = None
    day: int | None = None
    start: str | None = None
    end: str | None = None
    dates: list[str] = field(default_factory=list)
    ranges: list[dict[str, str]] = field(default_factory=list)
    grain: str | None = None
    weekdays: list[int] = field(default_factory=list)
    week_scope: str | None = None


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
            raise QueryIntentParseError("结构化意图必须是JSON对象", code="INVALID_ROOT_TYPE")
        allowed_fields = {
            "status", "metrics", "dimensions", "filters", "time", "group_by",
            "order_by", "limit", "message", "missing",
        }
        unknown_fields = set(payload) - allowed_fields
        if unknown_fields:
            raise QueryIntentParseError("结构化意图包含未知字段", code="UNKNOWN_FIELD")

        raw_status = payload.get("status", QueryIntentStatus.READY)
        try:
            status = QueryIntentStatus(raw_status)
        except ValueError as exc:
            raise QueryIntentParseError("不支持的意图状态", code="INVALID_STATUS") from exc

        time_payload = payload.get("time")
        time_intent = None
        if time_payload is None and "time" in payload:
            raise QueryIntentParseError(
                "time不得为null",
                code="TIME_NULL",
                status=QueryIntentStatus.NEEDS_CLARIFICATION,
            )
        if time_payload is not None and (
            not isinstance(time_payload, dict)
            or not isinstance(time_payload.get("expression"), str)
        ):
            raise QueryIntentParseError("time必须包含expression", code="INVALID_TIME_SCHEMA")
        if time_payload is not None:
            allowed_time_fields = {
                "expression", "kind", "year", "month", "day", "start", "end",
                "dates", "ranges", "grain", "weekdays", "week_scope",
            }
            unknown_fields = set(time_payload) - allowed_time_fields
            if unknown_fields:
                raise QueryIntentParseError("time包含未知字段", code="UNKNOWN_TIME_FIELD")
            try:
                time_intent = TimeIntent(**time_payload)
            except TypeError as exc:
                raise QueryIntentParseError("time结构类型错误", code="INVALID_TIME_TYPE") from exc
            if time_intent.kind not in {"relative", "absolute", "range", "set", "weekday_set", "periodic_weekday"}:
                raise QueryIntentParseError("time.kind不受支持")
            if time_intent.grain is not None and time_intent.grain not in {"day", "week", "month"}:
                raise QueryIntentParseError("time.grain不受支持")
            for field_name, value in (("year", time_intent.year), ("month", time_intent.month), ("day", time_intent.day)):
                if value is not None and not isinstance(value, int):
                    raise QueryIntentParseError("time日期组件类型错误", code="INVALID_TIME_TYPE")
            if time_intent.month is not None and not 1 <= time_intent.month <= 12:
                raise QueryIntentParseError("time.month必须在1到12之间")
            if time_intent.day is not None and not 1 <= time_intent.day <= 31:
                raise QueryIntentParseError("time.day必须在1到31之间")
            if not isinstance(time_intent.weekdays, list) or not all(isinstance(item, int) for item in time_intent.weekdays):
                raise QueryIntentParseError("time.weekdays必须是整数数组", code="INVALID_TIME_TYPE")
            if any(item < 0 or item > 6 for item in time_intent.weekdays):
                raise QueryIntentParseError("time.weekdays必须使用0到6，且0代表星期日")
            if time_intent.week_scope not in {None, "current"}:
                raise QueryIntentParseError("time.week_scope只支持current")
            if time_intent.kind == "weekday_set" and not time_intent.weekdays:
                raise QueryIntentParseError("weekday_set必须包含weekdays")
            if time_intent.kind == "weekday_set" and time_intent.week_scope is None:
                raise QueryIntentParseError(
                    "星期集合缺少周范围",
                    code="MISSING_WEEK_SCOPE",
                    status=QueryIntentStatus.NEEDS_CLARIFICATION,
                )
            if time_intent.kind == "periodic_weekday" and not time_intent.weekdays:
                raise QueryIntentParseError("周期星期筛选必须包含weekdays")
            if time_intent.kind in {"weekday_set", "periodic_weekday"} and (
                time_intent.dates or time_intent.ranges or time_intent.start or time_intent.end
            ):
                raise QueryIntentParseError("星期结构不能同时包含具体日期或区间")
            if time_intent.kind in {"weekday_set", "periodic_weekday"} and time_intent.grain not in {None, "day"}:
                raise QueryIntentParseError("星期结构的粒度必须是day")
            if any(value is not None for value in (time_intent.year, time_intent.month, time_intent.day)) and time_intent.kind == "set":
                raise QueryIntentParseError("日期集合不能同时包含year、month或day")
            if not isinstance(time_intent.dates, list) or not all(isinstance(item, str) for item in time_intent.dates):
                raise QueryIntentParseError("time.dates必须是日期字符串数组")
            if not isinstance(time_intent.ranges, list) or not all(isinstance(item, dict) for item in time_intent.ranges):
                raise QueryIntentParseError("time.ranges必须是对象数组")
            for item in time_intent.ranges:
                if set(item) - {"start", "end"} or not isinstance(item.get("start"), str) or not isinstance(item.get("end"), str):
                    raise QueryIntentParseError("time.ranges只允许包含start和end日期")
            for field_name, value in (("start", time_intent.start), ("end", time_intent.end)):
                if value is not None:
                    try:
                        date.fromisoformat(value)
                    except (TypeError, ValueError) as exc:
                        raise QueryIntentParseError("time日期格式非法", code="INVALID_DATE") from exc
            for value in time_intent.dates:
                try:
                    date.fromisoformat(value)
                except (TypeError, ValueError) as exc:
                    raise QueryIntentParseError("time.dates包含非法ISO日期", code="INVALID_DATE") from exc
            for item in time_intent.ranges:
                for field_name in ("start", "end"):
                    try:
                        date.fromisoformat(item[field_name])
                    except (TypeError, ValueError) as exc:
                        raise QueryIntentParseError("time.ranges包含非法ISO日期", code="INVALID_DATE") from exc
            if time_intent.start and not time_intent.end or time_intent.end and not time_intent.start:
                raise QueryIntentParseError("time.start和time.end必须同时提供")
            if time_intent.kind == "range" and (time_intent.dates or time_intent.ranges):
                raise QueryIntentParseError("range不能同时包含dates或ranges")

        limit = payload.get("limit")
        if limit is not None and (not isinstance(limit, int) or limit <= 0):
            raise QueryIntentParseError("limit必须是正整数", code="INVALID_LIMIT")

        for field_name in ("metrics", "dimensions", "group_by", "missing"):
            if not isinstance(payload.get(field_name, []), list) or not all(
                isinstance(item, str) for item in payload.get(field_name, [])
            ):
                raise QueryIntentParseError("结构化意图字段类型错误", code="INVALID_FIELD_TYPE")
        for field_name in ("filters", "order_by"):
            if not isinstance(payload.get(field_name, []), list) or not all(
                isinstance(item, dict) for item in payload.get(field_name, [])
            ):
                raise QueryIntentParseError("结构化意图字段类型错误", code="INVALID_FIELD_TYPE")
        if payload.get("message") is not None and not isinstance(payload.get("message"), str):
            raise QueryIntentParseError("结构化意图字段类型错误", code="INVALID_FIELD_TYPE")
        intent = cls(
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
        return intent


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise QueryIntentParseError("结构化意图字段类型错误", code="INVALID_FIELD_TYPE")
    return value


def _dict_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise QueryIntentParseError("结构化意图字段类型错误", code="INVALID_FIELD_TYPE")
    return value
