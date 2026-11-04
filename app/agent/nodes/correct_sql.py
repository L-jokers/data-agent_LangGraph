import inspect

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger
from app.services.sql_correction import determine_correction


async def correct_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """仅执行批准的结构化规范化，完整重跑由可信链路回调负责。"""
    writer = runtime.stream_writer
    attempt = state.get("correction_attempts", 0)
    decision = determine_correction(state["query_intent"], attempt=attempt)
    if not decision.applied or decision.intent is None:
        writer({"type": "progress", "step": "校正SQL", "status": "error"})
        logger.info("SQL未触发有限修正: %s", decision.reason)
        return {"error": decision.reason or "SQL_CORRECTION_NOT_ALLOWED"}

    snapshot = runtime.context.get("semantic_model_snapshot")
    if snapshot is None or state.get("semantic_version_id") != getattr(snapshot, "version_id", None):
        writer({"type": "progress", "step": "校正SQL", "status": "error"})
        return {"error": "TRUSTED_REPLAY_SNAPSHOT_INVALID"}
    chain = runtime.context.get("trusted_query_chain")
    if chain is None or not callable(chain):
        writer({"type": "progress", "step": "校正SQL", "status": "error"})
        return {"error": "TRUSTED_REPLAY_UNAVAILABLE"}
    try:
        parameters = inspect.signature(chain).parameters
        kwargs = {"attempt": attempt}
        if "resolved_time" in parameters:
            kwargs["resolved_time"] = state.get("resolved_time")
        if "semantic_version_id" in parameters:
            kwargs["semantic_version_id"] = state.get("semantic_version_id")
        run = await chain(state["query_intent"], **kwargs)
        if not getattr(run, "result", None) or getattr(run, "plan", None) is None or getattr(run, "compiled", None) is None:
            raise RuntimeError("TRUSTED_REPLAY_FAILED")
    except Exception as exc:
        logger.error("trusted query replay failed: %s", exc)
        writer({"type": "progress", "step": "校正SQL", "status": "error"})
        return {"error": "TRUSTED_REPLAY_FAILED"}
    writer({"type": "progress", "step": "校正SQL", "status": "success"})
    writer({"type": "sql", "sql": run.compiled.sql})
    return {
        "query_intent": decision.intent,
        "correction_attempts": attempt + 1,
        "correction_events": list(run.events),
        "query_plan": run.plan,
        "compiled_query": run.compiled,
        "sql": run.compiled.sql,
        "error": None,
    }
