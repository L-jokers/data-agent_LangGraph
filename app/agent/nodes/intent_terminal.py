from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.intent.models import QueryIntentStatus


async def intent_terminal(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """Emit clarification, unsupported, or error terminal events without running SQL."""
    intent = state.get("query_intent")
    error = state.get("error")
    if error:
        runtime.stream_writer({
            "type": "error",
            "code": error,
            "message": "查询无法安全执行",
        })
        runtime.stream_writer({"type": "done", "status": "error"})
        return {"terminal_status": "error"}

    status = intent.status
    if status == QueryIntentStatus.READY:
        status = QueryIntentStatus.UNSUPPORTED
        intent.message = intent.message or "当前问题未通过查询校验，未执行查询"
    event_type = (
        "clarification"
        if status == QueryIntentStatus.NEEDS_CLARIFICATION
        else "unsupported"
    )
    runtime.stream_writer({
        "type": event_type,
        "message": intent.message or "当前问题无法进入查询流程",
        "missing": intent.missing,
    })
    runtime.stream_writer({"type": "done", "status": status.value})
    return {"terminal_status": status.value}
