from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.intent.models import QueryIntent, QueryIntentStatus


@dataclass(frozen=True)
class CorrectionDecision:
    applied: bool
    intent: QueryIntent | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CorrectionRun:
    decision: CorrectionDecision
    result: Any | None
    compiled: Any | None
    events: tuple[str, ...]


def determine_correction(intent: QueryIntent, *, attempt: int) -> CorrectionDecision:
    """只规范明确的排序枚举，不改变指标、时间、过滤或粒度语义。"""
    if attempt >= 1:
        return CorrectionDecision(False, reason="CORRECTION_LIMIT_REACHED")
    if intent.status != QueryIntentStatus.READY:
        return CorrectionDecision(False, reason="INTENT_NOT_READY")
    if not intent.order_by:
        return CorrectionDecision(False, reason="NO_APPROVED_CORRECTION")

    corrected = deepcopy(intent)
    changed = False
    for item in corrected.order_by:
        direction = item.get("direction")
        if isinstance(direction, str) and direction in {"ASC", "DESC", "Asc", "Desc"}:
            item["direction"] = direction.lower()
            changed = True
    if not changed:
        return CorrectionDecision(False, reason="NO_APPROVED_CORRECTION")
    return CorrectionDecision(True, intent=corrected, reason="NORMALIZE_ORDER_DIRECTION")


async def rerun_after_correction(
    intent: QueryIntent,
    *,
    attempt: int,
    validate_intent: Callable[[QueryIntent], Awaitable[QueryIntent]],
    build_plan: Callable[[QueryIntent], Awaitable[Any]],
    validate_plan: Callable[[Any], Awaitable[Any]],
    compile_sql: Callable[[Any], Awaitable[Any]],
    validate_sql: Callable[[Any], Awaitable[Any]],
) -> CorrectionRun:
    decision = determine_correction(intent, attempt=attempt)
    if not decision.applied or decision.intent is None:
        return CorrectionRun(decision, None, None, ())

    events: list[str] = []
    reparsed = await validate_intent(decision.intent)
    events.append("intent_validation")
    plan = await build_plan(reparsed)
    events.append("plan_generation")
    validated_plan = await validate_plan(plan)
    events.append("plan_validation")
    compiled = await compile_sql(validated_plan)
    events.append("sql_compilation")
    result = await validate_sql(compiled)
    events.append("sql_security_validation")
    return CorrectionRun(decision, result, compiled, tuple(events))
