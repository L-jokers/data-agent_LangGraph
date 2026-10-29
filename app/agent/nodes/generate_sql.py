from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.compiler.sql_compiler import SQLCompilerError, compile_query
from app.core.log import logger
from app.security.query_limits import QueryLimits


async def generate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """Compile the validated semantic plan into deterministic MySQL SQL."""
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "生成SQL", "status": "running"})
    try:
        limits = runtime.context.get("query_limits", QueryLimits())
        compiled = compile_query(
            state["query_plan"],
            max_rows=limits.max_rows,
            timeout_seconds=limits.timeout_seconds,
            max_execution_time_ms=limits.max_execution_time_ms,
        )
        writer({"type": "progress", "step": "生成SQL", "status": "success"})
        logger.info("deterministic SQL compiled")
        return {"compiled_query": compiled, "sql": compiled.sql, "error": None}
    except (SQLCompilerError, KeyError) as exc:
        writer({"type": "progress", "step": "生成SQL", "status": "error"})
        logger.error("SQL compilation failed: %s", exc)
        return {"error": "QUERY_COMPILATION_FAILED"}
