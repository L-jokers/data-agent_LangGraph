from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


def sanitize_execution_error(exc: Exception) -> dict[str, str]:
    logger.debug("database query failed: %s", exc)
    return {"code": "QUERY_EXECUTION_FAILED", "message": "查询执行失败"}


def _is_empty_aggregate(sql: str, rows: list[dict]) -> bool:
    if len(rows) != 1 or not ("COUNT(" in sql or "SUM(" in sql):
        return False
    return all(
        value is None or value == 0 or value == "0" or value == "0.0"
        for value in rows[0].values()
    )


async def execute_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """Execute a validated query and emit result/error followed by one terminal event."""
    writer = runtime.stream_writer
    compiled = state["compiled_query"]
    dw_mysql_repository = runtime.context["dw_mysql_repository"]

    try:
        result = await dw_mysql_repository.execute_sql(
            compiled.sql,
            compiled.params,
            max_rows=compiled.max_rows,
            timeout_seconds=compiled.timeout_seconds,
        )
        rows = [] if _is_empty_aggregate(compiled.sql, result.rows) else result.rows
        writer({
            "type": "result",
            "rows": rows,
            "meta": {
                "truncated": result.truncated,
                "row_count": len(rows),
                "max_rows": result.max_rows,
                "empty": not rows,
                "message": "查询成功，但没有匹配数据" if not rows else None,
            },
        })
        writer({"type": "done", "status": "success"})
        logger.info("query returned %s rows", len(rows))
    except Exception as exc:
        writer({"type": "error", **sanitize_execution_error(exc)})
        writer({"type": "done", "status": "error"})
        return {"error": "QUERY_EXECUTION_FAILED"}
