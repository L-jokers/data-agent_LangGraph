from __future__ import annotations

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.intent.models import QueryIntentStatus
from app.services.semantic_candidate_retriever import CandidateResolution


def _candidate_id(resolution: CandidateResolution) -> str | None:
    if resolution.status in {"exact", "auto"} and len(resolution.candidates) == 1:
        return resolution.candidates[0].stable_id
    return None


async def resolve_semantic_candidates(
    state: DataAgentState,
    runtime: Runtime[DataAgentContext],
):
    """Resolve every semantic token before time/planning consumes the intent."""
    intent = state["query_intent"]
    if intent.status != QueryIntentStatus.READY:
        return {"semantic_candidates": {}}

    retriever = runtime.context.get("semantic_candidate_retriever")
    snapshot = runtime.context.get("semantic_model_snapshot")
    version_id = state.get("semantic_version_id")
    if retriever is None or snapshot is None or not version_id or snapshot.version_id != version_id:
        intent.status = QueryIntentStatus.UNSUPPORTED
        intent.message = "语义候选检索链路不可用或版本不一致。"
        intent.missing = ["SEMANTIC_RETRIEVER_UNAVAILABLE"]
        return {"query_intent": intent, "semantic_candidates": {}}

    resolutions: dict[str, list[dict[str, object]]] = {
        "metrics": [], "dimensions": [], "fields": [], "values": [], "order": [],
    }
    missing: list[str] = []

    async def resolve_token(bucket: str, token: str, semantic_types: list[str], dimension_id: str | None = None):
        result = await retriever.hybrid_search(
            token,
            semantic_types,
            version_id=version_id,
            session_version_id=version_id,
            dimension_id=dimension_id,
        )
        selected = next(
            (result[item] for item in semantic_types if item in result and result[item].status in {"exact", "auto"}),
            None,
        ) or next((result[item] for item in semantic_types if item in result), None)
        if selected is None:
            missing.append(f"UNRESOLVED_{bucket.upper()}:{token}")
            return None
        resolutions[bucket].append({
            "query": token,
            "status": selected.status,
            "reason": selected.reason,
            "candidates": selected.candidates,
        })
        if selected.status in {"clarification", "unresolved"}:
            missing.append(f"{selected.status.upper()}_{bucket.upper()}:{token}")
        return _candidate_id(selected)

    resolved_metrics = []
    for token in intent.metrics:
        stable_id = await resolve_token("metrics", token, ["metric"])
        if stable_id is not None:
            resolved_metrics.append(stable_id)

    resolved_dimensions = []
    for token in intent.dimensions:
        stable_id = await resolve_token("dimensions", token, ["dimension"])
        if stable_id is not None:
            resolved_dimensions.append(stable_id)

    resolved_group_by = []
    for token in intent.group_by:
        stable_id = await resolve_token("dimensions", token, ["dimension"])
        if stable_id is not None:
            resolved_group_by.append(stable_id)

    resolved_order_by = []
    for item in intent.order_by:
        field = item.get("field")
        if not isinstance(field, str):
            missing.append("INVALID_ORDER_FIELD")
            continue
        stable_id = await resolve_token("order", field, ["metric", "dimension"])
        if stable_id is not None:
            resolved_order_by.append({**item, "field": stable_id})

    resolved_filters = []
    for item in intent.filters:
        field = item.get("field")
        if not isinstance(field, str):
            missing.append("INVALID_FILTER_FIELD")
            continue
        dimension_id = await resolve_token("fields", field, ["dimension"])
        if dimension_id is None:
            continue
        value = item.get("value")
        if not isinstance(value, str):
            missing.append(f"INVALID_FILTER_VALUE:{field}")
            continue
        value_id = await resolve_token("values", value, ["filter_value"], dimension_id)
        if value_id is not None:
            resolved_filters.append({**item, "field": dimension_id, "value": value})

    if missing:
        intent.status = QueryIntentStatus.NEEDS_CLARIFICATION if any(item.startswith("CLARIFICATION_") for item in missing) else QueryIntentStatus.UNSUPPORTED
        intent.message = "语义候选无法确定，请补充或改写查询。"
        intent.missing = missing
        return {"query_intent": intent, "semantic_candidates": resolutions}

    intent.metrics = resolved_metrics
    intent.dimensions = resolved_dimensions
    intent.group_by = resolved_group_by
    intent.order_by = resolved_order_by
    intent.filters = resolved_filters
    return {"query_intent": intent, "semantic_candidates": resolutions}
