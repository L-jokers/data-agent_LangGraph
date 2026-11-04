from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger
from app.intent.llm_output import LLMOutputParseError, response_to_payload
from app.intent.models import QueryIntent, QueryIntentParseError, QueryIntentStatus
from app.intent.time_coverage import validate_time_extraction
from app.prompt.prompt_loader import load_prompt


async def parse_intent(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """Let the LLM extract raw intent; semantic IDs and business meaning resolve later."""
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "解析结构化意图", "status": "running"})
    stage = "model_invocation"
    try:
        from app.agent.llm import llm

        response = await llm.ainvoke(load_prompt("parse_intent") + state["query"])
        stage = "response_adaptation"
        payload = response_to_payload(response)
        stage = "schema_validation"
        intent = QueryIntent.from_payload(payload)
        stage = "time_completeness"
        validate_time_extraction(state["query"], intent)
        writer({"type": "progress", "step": "解析结构化意图", "status": "success"})
        return {"query_intent": intent}
    except (QueryIntentParseError, LLMOutputParseError, ValueError, TypeError) as exc:
        code = getattr(exc, "code", "INVALID_SCHEMA")
        logger.warning(
            "structured intent parsing failed stage={} code={} summary={}",
            stage,
            code,
            "response_rejected",
        )
        writer({"type": "progress", "step": "解析结构化意图", "status": "error"})
        error_status = getattr(exc, "status", QueryIntentStatus.UNSUPPORTED)
        if code.startswith("TIME_"):
            error_status = QueryIntentStatus.NEEDS_CLARIFICATION
        return {
            "query_intent": QueryIntent(
                status=error_status,
                message="无法解析为受支持的结构化查询意图。",
                missing=[code],
            )
        }
    except Exception:
        logger.warning(
            "structured intent parsing failed stage={} code={} summary={}",
            stage,
            "MODEL_OR_ADAPTER_FAILURE",
            "request_failed_closed",
        )
        writer({"type": "progress", "step": "解析结构化意图", "status": "error"})
        return {
            "query_intent": QueryIntent(
                status=QueryIntentStatus.UNSUPPORTED,
                message="无法解析为受支持的结构化查询意图。",
                missing=["MODEL_OR_ADAPTER_FAILURE"],
            )
        }
