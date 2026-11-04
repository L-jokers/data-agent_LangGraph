from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.compiler.sql_compiler import CompiledQuery, compile_query
from app.intent.models import QueryIntent, QueryIntentStatus
from app.planner.models import QueryPlan, QueryPlanError
from app.planner.planner import build_query_plan
from app.security.query_limits import QueryLimits
from app.security.sqlglot_validator import validate_compiled_query


class TrustedReplayError(ValueError):
    pass


@dataclass(frozen=True)
class TrustedReplayResult:
    events: tuple[str, ...]
    result: Any
    plan: QueryPlan
    compiled: CompiledQuery


def _intent_payload(intent: QueryIntent) -> dict[str, Any]:
    payload = asdict(intent)
    payload["status"] = intent.status.value
    return payload


def validate_query_plan(plan: QueryPlan, *, snapshot: Any, version_id: str | None) -> QueryPlan:
    if snapshot is None or not getattr(snapshot, "version_id", None):
        raise TrustedReplayError("SEMANTIC_SNAPSHOT_MISSING")
    if version_id != snapshot.version_id or plan.semantic_version_id != snapshot.version_id:
        raise TrustedReplayError("SEMANTIC_VERSION_CHANGED")
    if not plan.metrics or plan.limit <= 0:
        raise QueryPlanError("QUERY_PLAN_INVALID")
    return plan


class TrustedQueryChain:
    def __init__(self, *, snapshot: Any, query_limits: QueryLimits | None = None):
        self.snapshot = snapshot
        self.query_limits = query_limits or QueryLimits()

    async def __call__(
        self,
        intent: QueryIntent,
        *,
        attempt: int,
        resolved_time: dict[str, Any] | None = None,
        semantic_version_id: str | None = None,
    ) -> TrustedReplayResult:
        if attempt != 0:
            raise TrustedReplayError("CORRECTION_LIMIT_REACHED")
        if self.snapshot is None:
            raise TrustedReplayError("SEMANTIC_SNAPSHOT_MISSING")
        if semantic_version_id != self.snapshot.version_id:
            raise TrustedReplayError("SEMANTIC_VERSION_CHANGED")

        reparsed = QueryIntent.from_payload(_intent_payload(intent))
        if reparsed.status != QueryIntentStatus.READY:
            raise TrustedReplayError("INTENT_NOT_READY")
        events = ["intent_validation"]

        plan = build_query_plan(self.snapshot, reparsed, resolved_time)
        events.append("plan_generation")
        plan = validate_query_plan(plan, snapshot=self.snapshot, version_id=semantic_version_id)
        events.append("plan_validation")

        compiled = compile_query(
            plan,
            max_rows=self.query_limits.max_rows,
            timeout_seconds=self.query_limits.timeout_seconds,
            max_execution_time_ms=self.query_limits.max_execution_time_ms,
        )
        events.append("sql_compilation")
        validate_compiled_query(compiled, snapshot=self.snapshot, plan=plan)
        events.append("sql_security_validation")
        return TrustedReplayResult(tuple(events), True, plan, compiled)