from dataclasses import dataclass
from typing import Any

from app.services.semantic_model_snapshot import SemanticModelSnapshot


MAX_DEPENDENCY_DEPTH = 2


@dataclass(frozen=True)
class MetricValidationIssue:
    code: str
    message: str
    metric_id: str
    missing: tuple[str, ...] = ()
    status: str = "unsupported"


class MetricDependencyValidationError(ValueError):
    def __init__(self, issue: MetricValidationIssue):
        super().__init__(issue.message)
        self.issue = issue
        self.code = issue.code
        self.status = issue.status
        self.missing = list(issue.missing)


def validate_metric_dependencies(
    snapshot: SemanticModelSnapshot,
    metric_ids: list[str],
    *,
    query_grain: str | None = None,
) -> None:
    """Validate the requested metric closure inside one immutable snapshot.

    Depth is the number of dependency edges from the requested metric to its
    deepest base metric. A direct base reference is depth 1; a base metric
    itself has depth 0.
    """
    metrics = {metric.id: metric for metric in snapshot.metrics}
    dependencies = {}
    for item in snapshot.metric_dependencies:
        if item.version_id != snapshot.version_id:
            raise _error("CROSS_VERSION_REFERENCE", "指标依赖跨越语义版本", item.metric_id)
        dependencies.setdefault(item.metric_id, []).append(item.depends_on_metric_id)

    for metric_id in metric_ids:
        if metric_id not in metrics:
            raise _error("UNKNOWN_METRIC", f"指标引用不存在: {metric_id}", metric_id)
        _walk_metric(snapshot, metric_id, metrics, dependencies, [], 0, query_grain, is_root=True)


def _walk_metric(snapshot, metric_id, metrics, dependencies, path, depth, query_grain, *, is_root=False):
    metric = metrics.get(metric_id)
    if metric is None:
        parent = path[-1] if path else metric_id
        raise _error("UNKNOWN_DEPENDENCY", f"指标依赖不存在: {metric_id}", parent)
    if metric.version_id != snapshot.version_id:
        raise _error("CROSS_VERSION_REFERENCE", f"指标 {metric_id} 不属于当前语义版本", metric_id)
    if metric.status not in {None, "active"}:
        raise _error("METRIC_NOT_ACTIVE", f"指标 {metric_id} 当前状态不可查询: {metric.status}", metric_id)
    if metric_id in path:
        cycle = " -> ".join(path + [metric_id])
        raise _error("DEPENDENCY_CYCLE", f"检测到指标循环依赖: {cycle}", metric_id)
    if depth > MAX_DEPENDENCY_DEPTH:
        raise _error("DEPENDENCY_DEPTH_EXCEEDED", f"指标 {metric_id} 的依赖深度超过{MAX_DEPENDENCY_DEPTH}", metric_id)

    _validate_metric_definition(metric, query_grain)
    if not is_root and getattr(metric, "metric_type", None) == "window":
        raise _error("WINDOW_AS_INPUT", f"窗口指标 {metric_id} 不得作为其他指标输入", metric_id)

    child_path = path + [metric_id]
    for dependency_id in dependencies.get(metric_id, []):
        if dependency_id == metric_id:
            raise _error("DEPENDENCY_CYCLE", f"指标 {metric_id} 直接依赖自身", metric_id)
        dependency = metrics.get(dependency_id)
        if dependency is None:
            raise _error("UNKNOWN_DEPENDENCY", f"指标 {metric_id} 引用了不存在的指标 {dependency_id}", metric_id)
        if dependency.version_id != snapshot.version_id:
            raise _error("CROSS_VERSION_REFERENCE", f"指标依赖 {dependency_id} 跨越语义版本", metric_id)
        _walk_metric(snapshot, dependency_id, metrics, dependencies, child_path, depth + 1, query_grain)
        if getattr(metric, "aggregation", None) and getattr(dependency, "aggregation", None):
            if metric.aggregation.casefold() == dependency.aggregation.casefold() and metric.metric_type != "ratio":
                raise _error("DUPLICATE_AGGREGATION", f"指标 {metric_id} 重复聚合依赖 {dependency_id}", metric_id)


def _validate_metric_definition(metric: Any, query_grain: str | None) -> None:
    metric_type = (getattr(metric, "metric_type", None) or "").casefold()
    dependencies_required = metric_type in {"derived", "ratio", "calculated", "window"} or bool(
        getattr(metric, "expression_ast", None)
    )
    missing: list[str] = []
    if not getattr(metric, "base_dataset", None):
        missing.append("来源数据集")
    if dependencies_required:
        if not getattr(metric, "grain", None):
            missing.append("统计粒度")
        if not getattr(metric, "period", None):
            missing.append("统计周期")
        if not getattr(metric, "business_scope", None):
            missing.append("业务限定")
        if not getattr(metric, "aggregation", None):
            missing.append("聚合方式")
        if not (getattr(metric, "expression_ast", None) or getattr(metric, "expression", None)):
            missing.append("表达式")
    elif not (getattr(metric, "relevant_columns", None) or getattr(metric, "expression", None)):
        missing.append("来源字段")
    if missing:
        raise _error(
            "METRIC_DEFINITION_INCOMPLETE",
            f"指标 {metric.id} 缺少定义: {', '.join(missing)}",
            metric.id,
            missing=missing,
            status="needs_clarification",
        )
    if query_grain and getattr(metric, "grain", None) and metric.grain != query_grain:
        raise _error("GRAIN_CONFLICT", f"指标 {metric.id} 的粒度 {metric.grain} 与查询粒度 {query_grain} 冲突", metric.id)
    if getattr(metric, "stage", None) == "filter" and metric_type in {"derived", "ratio", "window"}:
        raise _error("ILLEGAL_STAGE_DEPENDENCY", f"指标 {metric.id} 不能在过滤阶段作为派生输入", metric.id)


def _error(code, message, metric_id, *, missing=(), status="unsupported"):
    return MetricDependencyValidationError(
        MetricValidationIssue(code, message, metric_id, tuple(missing), status)
    )
