from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


async def correct_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """阶段四禁用自动SQL改写，避免任何路径绕过完整规划和安全校验。"""
    runtime.stream_writer({"type": "progress", "step": "校正SQL", "status": "error"})
    logger.info("SQL自动校正已禁用")
    return {"error": "SQL_AUTO_CORRECTION_DISABLED"}
