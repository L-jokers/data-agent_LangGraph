
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger
from app.intent.models import QueryIntentStatus
from app.planner.models import QueryPlanError
from app.planner.planner import build_query_plan


async def plan_query(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """根据版本化语义配置生成查询计划，不接受LLM指定物理表、字段或JOIN。"""
    intent = state["query_intent"]
    try:
        snapshot = runtime.context["semantic_model_snapshot"]
        query_plan = build_query_plan(
            snapshot,
            intent,
            state.get("resolved_time"),
        )
        runtime.stream_writer({
            "type": "progress",
            "step": "生成查询计划",
            "status": "success",
        })
        return {"query_plan": query_plan}
    except (QueryPlanError, ValueError) as exc:
        logger.info(f"查询计划校验失败: {exc}")
        intent.status = QueryIntentStatus(getattr(exc, "status", QueryIntentStatus.UNSUPPORTED))
        intent.message = str(exc)
        intent.missing = list(getattr(exc, "missing", [])) or [getattr(exc, "code", "QUERY_PLAN_INVALID")]
        runtime.stream_writer({
            "type": "progress",
            "step": "生成查询计划",
            "status": "error",
        })
        return {"query_intent": intent, "query_plan": None}
