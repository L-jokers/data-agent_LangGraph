import re

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger
from app.intent.models import QueryIntent, QueryIntentParseError, QueryIntentStatus
from app.intent.llm_output import response_to_payload
from app.prompt.prompt_loader import load_prompt


_METRIC_PHRASES = (
    ("订单实付金额", "paid_amount"),
    ("实付金额", "paid_amount"),
    ("商品购买数量", "product_quantity"),
    ("购买数量", "product_quantity"),
    ("销售数量", "product_quantity"),
    ("件数", "product_quantity"),
    ("订单数", "order_count"),
    ("订单量", "order_count"),
    ("平均每单购买件数", "average_quantity_per_order"),
    ("AOV", "average_quantity_per_order"),
)
_DIMENSION_PHRASES = (
    ("各大区", "region_name"),
    ("大区", "region_name"),
    ("地区", "region_name"),
    ("商品名称", "product_name"),
    ("商品", "product_name"),
    ("客户名称", "customer_name"),
    ("客户", "customer_name"),
)


def _known_intent(query: str) -> QueryIntent | None:
    upper_query = query.upper()
    if "GMV" in upper_query:
        return QueryIntent.from_payload({
            "status": "needs_clarification",
            "message": "GMV 不自动映射为订单实付金额，请明确指标口径。",
            "missing": ["指标口径"],
        })
    if "去年同期" in query or "本季度累计" in query:
        return QueryIntent.from_payload({
            "status": "unsupported",
            "message": "当前不支持该时间表达式。",
        })

    metrics = []
    for phrase, metric_id in _METRIC_PHRASES:
        if phrase in query and metric_id not in metrics:
            metrics.append(metric_id)
    dimensions = []
    for phrase, dimension_id in _DIMENSION_PHRASES:
        if phrase in query and dimension_id not in dimensions:
            dimensions.append(dimension_id)
    if any(phrase in query for phrase in ("商品购买数量", "购买数量", "销售数量", "件数")):
        dimensions = [dimension_id for dimension_id in dimensions if dimension_id != "product_name"]
    if not any(phrase in query for phrase in ("客户名称", "客户")):
        dimensions = [dimension_id for dimension_id in dimensions if dimension_id != "customer_name"]
    if not metrics:
        return None

    year_match = re.search(r"(20\d{2})\s*年", query)
    month_match = re.search(r"(1[0-2]|0?[1-9])\s*月", query)
    if month_match and not year_match:
        return QueryIntent.from_payload({
            "status": "needs_clarification",
            "metrics": metrics,
            "dimensions": dimensions,
            "group_by": dimensions,
            "message": "请补充年份。",
            "missing": ["年份"],
        })

    time = None
    if year_match and month_match:
        time = {
            "expression": f"{year_match.group(1)}年{int(month_match.group(1))}月",
            "kind": "absolute",
            "year": int(year_match.group(1)),
            "month": int(month_match.group(1)),
        }

    order_by = []
    if "按实付金额降序" in query or "按订单实付金额降序" in query:
        order_by = [{"field": "订单实付金额", "direction": "desc"}]
    return QueryIntent.from_payload({
        "status": "ready",
        "metrics": metrics,
        "dimensions": dimensions,
        "group_by": dimensions,
        "order_by": order_by,
        "time": time,
    })


async def parse_intent(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """Parse fixed project phrases deterministically, then use the LLM for other wording."""
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "解析结构化意图", "status": "running"})
    known_intent = _known_intent(state["query"])
    if known_intent is not None:
        writer({"type": "progress", "step": "解析结构化意图", "status": "success"})
        return {"query_intent": known_intent}
    try:
        from app.agent.llm import llm

        response = await llm.ainvoke(load_prompt("parse_intent") + state["query"])
        payload = response_to_payload(response)
        intent = QueryIntent.from_payload(payload)
        if "GMV" in state["query"].upper() or any("GMV" in metric.upper() for metric in intent.metrics):
            intent.status = QueryIntentStatus.NEEDS_CLARIFICATION
            intent.message = "GMV 不自动映射为订单实付金额，请明确指标口径。"
            intent.missing = ["指标口径"]
        writer({"type": "progress", "step": "解析结构化意图", "status": "success"})
        return {"query_intent": intent}
    except (QueryIntentParseError, ValueError, TypeError) as exc:
        logger.warning("structured intent parsing failed: %s", exc)
        writer({"type": "progress", "step": "解析结构化意图", "status": "error"})
        return {
            "query_intent": QueryIntent(
                status=QueryIntentStatus.UNSUPPORTED,
                message="无法解析为受支持的结构化查询意图。",
            )
        }
