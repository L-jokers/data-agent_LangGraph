from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from datetime import timezone

from app.intent.models import TimeIntent


BUSINESS_TIMEZONE = timezone(timedelta(hours=8), name="UTC+8")


class TimeParseError(ValueError):
    def __init__(self, message: str, *, code: str = "TIME_UNSUPPORTED", status: str = "unsupported"):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ResolvedTimeRange:
    start: date
    end: date
    grain: str
    expression: str

    def as_dict(self) -> dict[str, str]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "grain": self.grain,
            "expression": self.expression,
            "timezone": "UTC+8",
        }


@dataclass(frozen=True)
class ResolvedTimeSet:
    dates: tuple[date, ...]
    ranges: tuple[ResolvedTimeRange, ...]
    grain: str
    expression: str

    @property
    def start(self) -> date:
        if self.dates and not self.ranges:
            return self.dates[0]
        if self.ranges and not self.dates:
            return self.ranges[0].start
        raise TimeParseError("时间集合包含多个不连续成员，不能读取单一start")

    @property
    def end(self) -> date:
        if self.dates and not self.ranges:
            return self.dates[-1]
        if self.ranges and not self.dates:
            return self.ranges[-1].end
        raise TimeParseError("时间集合包含多个不连续成员，不能读取单一end")

    def as_dict(self) -> dict:
        values = {
            "dates": [item.isoformat() for item in self.dates],
            "ranges": [item.as_dict() for item in self.ranges],
            "grain": self.grain,
            "expression": self.expression,
            "timezone": "UTC+8",
        }
        if len(self.dates) == 1 and not self.ranges:
            values.update({"start": self.dates[0].isoformat(), "end": self.dates[0].isoformat()})
        elif len(self.ranges) == 1 and not self.dates:
            values.update({"start": self.ranges[0].start.isoformat(), "end": self.ranges[0].end.isoformat()})
        return values


def resolve_time_intent(time_intent: TimeIntent, reference_time: datetime) -> ResolvedTimeSet:
    reference_date = _as_business_date(reference_time)
    expression = time_intent.expression.strip()
    if not expression:
            raise TimeParseError("时间表达式不能为空")

    if time_intent.kind == "periodic_weekday":
        raise TimeParseError("周期星期筛选暂不支持，不能按本周日期替代", code="PERIODIC_WEEKDAY_UNSUPPORTED")

    if time_intent.kind == "weekday_set":
        return _resolve_weekday_set(time_intent, reference_date, expression)

    if time_intent.kind == "set" or time_intent.dates or time_intent.ranges:
        return _resolve_explicit_set(time_intent, expression)

    absolute = _resolve_absolute(time_intent, expression)
    if absolute:
        return ResolvedTimeSet((), (absolute,), absolute.grain, expression)

    if expression in {"今天", "今日"}:
        return _single_date(reference_date, expression)
    if expression in {"昨天", "昨日"}:
        target = reference_date - timedelta(days=1)
        return _single_date(target, expression)
    if expression in {"前天"}:
        target = reference_date - timedelta(days=2)
        return _single_date(target, expression)
    if expression in {"本月", "这个月", "当月"}:
        return _as_set(_month_range(reference_date.year, reference_date.month, expression))
    if expression in {"上个月", "上月", "上一个月"}:
        target = reference_date.replace(day=1) - timedelta(days=1)
        return _as_set(_month_range(target.year, target.month, expression))

    match = re.fullmatch(r"(?:最近|过去)\s*(\d+)\s*天", expression)
    if match:
        days = int(match.group(1))
        if days <= 0:
            raise TimeParseError("最近天数必须大于零")
        return _as_set(ResolvedTimeRange(
            reference_date - timedelta(days=days - 1),
            reference_date,
            "day",
            expression,
        ))

    if expression in {"本周", "这周", "本星期", "这星期"}:
        start = reference_date - timedelta(days=(reference_date.weekday() + 1) % 7)
        return _as_set(ResolvedTimeRange(start, start + timedelta(days=6), "week", expression))

    raise TimeParseError(f"不支持的时间表达式: {expression}")


def _resolve_absolute(time_intent: TimeIntent, expression: str) -> ResolvedTimeRange | None:
    if time_intent.kind == "range" and time_intent.start and time_intent.end:
        start = date.fromisoformat(time_intent.start)
        end = date.fromisoformat(time_intent.end)
        if end < start:
            raise TimeParseError("时间范围结束日期不能早于开始日期")
        return ResolvedTimeRange(start, end, "day", expression)

    if time_intent.year is not None and time_intent.month is not None:
        if not 1 <= time_intent.month <= 12:
            raise TimeParseError("月份必须在1到12之间")
        if time_intent.day is not None:
            target = date(time_intent.year, time_intent.month, time_intent.day)
            return ResolvedTimeRange(target, target, "day", expression)
        return _month_range(time_intent.year, time_intent.month, expression)

    if re.fullmatch(r"\d{4}\s*年\s*\d{1,2}\s*月", expression):
        year, month = map(int, re.findall(r"\d+", expression))
        return _month_range(year, month, expression)

    if re.fullmatch(r"\d{1,2}\s*月", expression):
        raise TimeParseError("月份缺少年份，需要澄清年份", code="MISSING_YEAR", status="needs_clarification")
    return None


def _single_date(value: date, expression: str) -> ResolvedTimeSet:
    return ResolvedTimeSet((value,), (), "day", expression)


def _as_set(value: ResolvedTimeRange) -> ResolvedTimeSet:
    return ResolvedTimeSet((), (value,), value.grain, value.expression)


def _resolve_explicit_set(time_intent: TimeIntent, expression: str) -> ResolvedTimeSet:
    if not time_intent.dates and not time_intent.ranges and not time_intent.start and not time_intent.end:
        raise TimeParseError("时间集合不能为空")
    dates = sorted({date.fromisoformat(value) for value in time_intent.dates})
    if len(dates) > 7:
        raise TimeParseError("离散日期最多支持7个")
    ranges: list[ResolvedTimeRange] = []
    raw_ranges = list(time_intent.ranges)
    if time_intent.start or time_intent.end:
        raw_ranges.append({"start": time_intent.start, "end": time_intent.end})
    for item in raw_ranges:
        if not isinstance(item.get("start"), str) or not isinstance(item.get("end"), str):
            raise TimeParseError("连续区间必须包含start和end")
        start = date.fromisoformat(item["start"])
        end = date.fromisoformat(item["end"])
        if end < start:
            raise TimeParseError("时间范围结束日期不能早于开始日期")
        ranges.append(ResolvedTimeRange(start, end, "day", expression))
    ranges.sort(key=lambda item: (item.start, item.end))
    merged: list[ResolvedTimeRange] = []
    for item in ranges:
        if merged and item.start <= merged[-1].end + timedelta(days=1):
            previous = merged[-1]
            merged[-1] = ResolvedTimeRange(previous.start, max(previous.end, item.end), "day", expression)
        else:
            merged.append(item)
    if len(merged) > 5:
        raise TimeParseError("连续区间最多支持5个")
    return ResolvedTimeSet(tuple(dates), tuple(merged), "day", expression)


def _resolve_weekday_set(time_intent: TimeIntent, reference_date: date, expression: str) -> ResolvedTimeSet:
    if time_intent.week_scope != "current":
        raise TimeParseError("星期集合缺少周范围，需要澄清具体哪一周", code="MISSING_WEEK_SCOPE", status="needs_clarification")
    if not time_intent.weekdays:
        raise TimeParseError("星期集合为空", code="EMPTY_WEEKDAY_SET")
    week_start = reference_date - timedelta(days=(reference_date.weekday() + 1) % 7)
    dates = tuple(sorted({week_start + timedelta(days=weekday) for weekday in time_intent.weekdays}))
    if len(dates) > 7:
        raise TimeParseError("离散日期最多支持7个", code="TOO_MANY_DATES", status="needs_clarification")
    return ResolvedTimeSet(dates, (), "day", expression)


def _month_range(year: int, month: int, expression: str) -> ResolvedTimeRange:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return ResolvedTimeRange(start, end, "month", expression)


def _as_business_date(reference_time: datetime) -> date:
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=BUSINESS_TIMEZONE)
    return reference_time.astimezone(BUSINESS_TIMEZONE).date()
