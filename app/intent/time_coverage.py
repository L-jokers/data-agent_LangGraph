import re

from app.intent.models import QueryIntent, QueryIntentParseError, QueryIntentStatus


TIME_MARKER_RE = re.compile(
    r"\d{4}\s*年|\d{1,2}\s*月|\d{1,2}\s*[日号]|今天|今日|昨天|昨日|前天|本周|这周|上周|下周|"
    r"本月|这个月|上个月|最近\s*\d+\s*天|过去\s*\d+\s*天|星期[一二三四五六日天]|周[一二三四五六日天]|"
    r"从[^，。；;]*?到[^，。；;]*|日期|期间"
)


def validate_time_extraction(query: str, intent: QueryIntent) -> None:
    """Reject omitted or visibly partial time extraction without claiming full NLP coverage."""
    markers = [match.group(0) for match in TIME_MARKER_RE.finditer(query)]
    if not markers:
        return
    if intent.time is None:
        raise QueryIntentParseError(
            "检测到时间条件但结构化输出为空",
            code="TIME_OMITTED",
            status=QueryIntentStatus.NEEDS_CLARIFICATION,
        )
    expression = intent.time.expression.strip()
    normalized_query = _normalize(query)
    normalized_expression = _normalize(expression)
    uncovered = [marker for marker in markers if _normalize(marker) not in normalized_expression]
    if uncovered and not _has_structural_coverage(intent):
        raise QueryIntentParseError(
            f"时间结构未覆盖原问题中的表达: {'、'.join(uncovered)}",
            code="TIME_PARTIAL",
            status=QueryIntentStatus.NEEDS_CLARIFICATION,
        )
    if normalized_expression and normalized_expression not in normalized_query:
        raise QueryIntentParseError(
            "结构化时间表达与用户原文不一致",
            code="TIME_CONTRADICTORY",
            status=QueryIntentStatus.NEEDS_CLARIFICATION,
        )


def _has_structural_coverage(intent: QueryIntent) -> bool:
    time = intent.time
    if time is None:
        return False
    return bool(time.dates or time.ranges or time.weekdays or time.start or time.end or time.year or time.month or time.day)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
