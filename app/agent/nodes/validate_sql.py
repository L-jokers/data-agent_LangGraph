from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger
from app.security.sqlglot_validator import SQLSecurityError, validate_compiled_query


async def validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """Run the independent SQLGlot allowlist check before exposing or executing SQL."""
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "验证SQL", "status": "running"})
    compiled = state.get("compiled_query")
    try:
        if compiled is None:
            raise SQLSecurityError("missing compiled SQL")
        validate_compiled_query(compiled)
        writer({"type": "progress", "step": "验证SQL", "status": "success"})
        writer({"type": "sql", "sql": compiled.sql})
        logger.info("SQL AST validation succeeded")
        return {"error": None}
    except SQLSecurityError as exc:
        writer({"type": "progress", "step": "验证SQL", "status": "error"})
        logger.error("SQL validation failed: %s", exc)
        return {"error": "SQL_SECURITY_VALIDATION_FAILED"}
