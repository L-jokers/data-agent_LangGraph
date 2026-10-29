from datetime import datetime

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger
from app.intent.models import QueryIntentStatus
from app.time.parser import TimeParseError, resolve_time_intent
from app.time.parser import BUSINESS_TIMEZONE


async def resolve_time(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """使用确定性规则和UTC+8参考时间，将意图中的时间表达式解析为绝对范围。"""
    intent = state["query_intent"]
    if intent.status != QueryIntentStatus.READY:
        return {}
    if intent.time is None:
        return {"resolved_time": None}
    reference_time = runtime.context.get("reference_time") or datetime.now(BUSINESS_TIMEZONE)
    try:
        resolved = resolve_time_intent(intent.time, reference_time)
        return {"resolved_time": resolved.as_dict()}
    except (TimeParseError, ValueError) as exc:
        logger.info(f"时间表达式需要澄清或不支持: {exc}")
        message = str(exc)
        status = QueryIntentStatus.NEEDS_CLARIFICATION if "缺少年份" in message else QueryIntentStatus.UNSUPPORTED
        intent.status = status
        intent.message = message
        return {"query_intent": intent, "resolved_time": None}
