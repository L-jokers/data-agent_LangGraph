from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from datetime import timezone

from app.intent.models import TimeIntent


BUSINESS_TIMEZONE = timezone(timedelta(hours=8), name="UTC+8")


class TimeParseError(ValueError):
    pass


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


def resolve_time_intent(time_intent: TimeIntent, reference_time: datetime) -> ResolvedTimeRange:
    reference_date = _as_business_date(reference_time)
    expression = time_intent.expression.strip()
    if not expression:
            raise TimeParseError("时间表达式不能为空")

    absolute = _resolve_absolute(time_intent, expression)
    if absolute:
        return absolute

    if expression in {"今天", "今日"}:
        return ResolvedTimeRange(reference_date, reference_date, "day", expression)
    if expression in {"昨天", "昨日"}:
        target = reference_date - timedelta(days=1)
        return ResolvedTimeRange(target, target, "day", expression)
    if expression in {"前天"}:
        target = reference_date - timedelta(days=2)
        return ResolvedTimeRange(target, target, "day", expression)
    if expression in {"本月", "这个月", "当月"}:
        return _month_range(reference_date.year, reference_date.month, expression)
    if expression in {"上个月", "上月", "上一个月"}:
        target = reference_date.replace(day=1) - timedelta(days=1)
        return _month_range(target.year, target.month, expression)

    match = re.fullmatch(r"(?:最近|过去)\s*(\d+)\s*天", expression)
    if match:
        days = int(match.group(1))
        if days <= 0:
            raise TimeParseError("最近天数必须大于零")
        return ResolvedTimeRange(
            reference_date - timedelta(days=days - 1),
            reference_date,
            "day",
            expression,
        )

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
        raise TimeParseError("月份缺少年份，需要澄清年份")
    return None


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
