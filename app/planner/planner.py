from collections import deque
from typing import Any

from app.conf.meta_config import (
    DimensionConfig,
    MetaConfig,
    MetricConfig,
    RelationshipConfig,
    TimeDimensionConfig,
)
from app.intent.models import QueryIntent, QueryIntentStatus
from app.planner.models import (
    DimensionPlan,
    FilterPlan,
    JoinPlan,
    MetricPlan,
    OrderPlan,
    QueryPlan,
    QueryPlanError,
    TimeConditionPlan,
    TimePlan,
)


SUPPORTED_FILTER_OPERATORS = {"eq", "in", "gte", "lte", "contains"}
MAX_LIMIT = 1000


def build_query_plan(
    config: MetaConfig,
    intent: QueryIntent,
    resolved_time: dict[str, str] | None = None,
) -> QueryPlan:
    """将结构化意图编译为SQL阶段可消费的确定性查询计划。

    这里不让LLM直接决定物理表、字段、JOIN或聚合表达式，而是从
    ``conf/meta_config.yaml`` 加载的 ``MetaConfig`` 中解析稳定ID、业务名称
    和别名，生成后续SQL编译所需的完整中间结构：数据集、指标、维度、
    关系路径、过滤条件、时间条件、排序、limit以及聚合定义。
    """
    if intent.status != QueryIntentStatus.READY:
        raise QueryPlanError("非ready意图不能生成查询计划")

    config.validate()
    dataset = _only_dataset(config)
    metrics = tuple(_resolve_metrics(config, intent.metrics))
    if not metrics:
        raise QueryPlanError("查询计划至少需要一个指标")
    metric_configs = {metric_config.id: metric_config for metric_config in config.metrics}
    for metric in metrics:
        if metric_configs[metric.id].base_dataset != dataset.id:
            raise QueryPlanError(f"指标不属于当前数据集: {metric.id}")

    dimensions = tuple(_resolve_dimensions(config, intent.dimensions + intent.group_by))
    filters = tuple(_resolve_filters(config, intent.filters))
    time_plan = _build_time_plan(config, resolved_time)
    required_tables = {
        dimension.table for dimension in dimensions
    } | {filter_plan.table for filter_plan in filters}
    if time_plan:
        required_tables.add(time_plan.table)
    joins = tuple(_resolve_join_path(config, dataset.table, required_tables))
    order_by = tuple(_resolve_order_by(intent, metrics, dimensions))
    limit_explicit = intent.limit is not None
    limit = intent.limit if limit_explicit else 100
    if limit <= 0 or limit > MAX_LIMIT:
        raise QueryPlanError(f"limit必须在1到{MAX_LIMIT}之间")

    aggregations = {metric.id: _aggregation_for(metric) for metric in metrics}
    return QueryPlan(
        dataset_id=dataset.id,
        fact_table=dataset.table,
        metrics=metrics,
        dimensions=dimensions,
        joins=joins,
        filters=filters,
        time=time_plan,
        order_by=order_by,
        limit=limit,
        limit_explicit=limit_explicit,
        aggregations=aggregations,
    )


def _only_dataset(config: MetaConfig):
    if len(config.datasets) != 1:
        raise QueryPlanError("当前单轮模型必须且只能有一个数据集")
    return config.datasets[0]


def _resolve_metrics(config: MetaConfig, requested: list[str]) -> list[MetricPlan]:
    """按语义配置解析指标，并保留配置中的聚合依赖信息。"""
    result: list[MetricPlan] = []
    for token in _unique(requested):
        metric = _resolve_one(
            token,
            config.metrics,
            lambda item: [item.id, item.name, *item.aliases],
            "指标",
        )
        result.append(MetricPlan(
            id=metric.id,
            name=metric.name,
            metric_type=metric.type,
            expression=metric.expression,
            numerator=metric.numerator,
            denominator=metric.denominator,
            aliases=tuple(metric.aliases),
        ))
    return result


def _resolve_dimensions(config: MetaConfig, requested: list[str]) -> list[DimensionPlan]:
    """按语义配置解析维度，输出受白名单约束的物理表列映射。"""
    result: list[DimensionPlan] = []
    for token in _unique(requested):
        dimension = _resolve_one(
            token,
            config.dimensions,
            lambda item: [item.id, item.name, *item.aliases],
            "维度",
        )
        result.append(DimensionPlan(
            id=dimension.id,
            name=dimension.name,
            table=dimension.table,
            column=dimension.column,
            aliases=tuple(dimension.aliases),
        ))
    return result


def _resolve_filters(config: MetaConfig, filters: list[dict[str, Any]]) -> list[FilterPlan]:
    """把意图过滤条件映射为配置允许的维度字段和值条件。

    过滤字段必须先在语义维度配置中解析成功，不能接受意图直接携带的
    任意物理字段；这样SQL编译阶段只需消费已校验的表名、列名和操作符。
    """
    result: list[FilterPlan] = []
    for raw_filter in filters:
        field = raw_filter.get("field")
        operator = raw_filter.get("operator")
        if not isinstance(field, str) or not isinstance(operator, str):
            raise QueryPlanError("过滤条件必须包含field和operator")
        if operator not in SUPPORTED_FILTER_OPERATORS:
            raise QueryPlanError(f"不支持的过滤操作符: {operator}")
        dimension = _resolve_one(
            field,
            config.dimensions,
            lambda item: [item.id, item.name, *item.aliases],
            "过滤维度",
        )
        if "value" not in raw_filter:
            raise QueryPlanError(f"过滤条件缺少value: {field}")
        result.append(FilterPlan(
            field_id=dimension.id,
            table=dimension.table,
            column=dimension.column,
            operator=operator,
            value=raw_filter["value"],
        ))
    return result


def _build_time_plan(config: MetaConfig, resolved_time: dict[str, str] | None) -> TimePlan | None:
    """根据语义时间维度配置生成SQL时间条件。

    对月份粒度显式生成年份和月份两个条件，避免仅按月份过滤导致跨年
    数据混入；其他粒度使用配置中的日期键生成闭区间起止条件。
    """
    if not resolved_time:
        return None
    if len(config.time_dimensions) != 1:
        raise QueryPlanError("当前模型必须且只能有一个时间维度")
    time_dimension: TimeDimensionConfig = config.time_dimensions[0]
    start = resolved_time.get("start")
    end = resolved_time.get("end")
    grain = resolved_time.get("grain")
    if not start or not end or not grain:
        raise QueryPlanError("解析后的时间范围缺少start、end或grain")
    if grain not in time_dimension.supported_grains:
        raise QueryPlanError(f"时间粒度不支持: {grain}")

    if grain == "month":
        start_year, start_month = int(start[:4]), int(start[5:7])
        end_year, end_month = int(end[:4]), int(end[5:7])
        if (start_year, start_month) != (end_year, end_month):
            raise QueryPlanError("月份计划必须对应单一年月")
        conditions = (
            TimeConditionPlan(f"{time_dimension.table}.{time_dimension.year_field}", "eq", start_year),
            TimeConditionPlan(f"{time_dimension.table}.{time_dimension.month_field}", "eq", start_month),
        )
    else:
        conditions = (
            TimeConditionPlan(f"{time_dimension.table}.{time_dimension.date_key_field}", "gte", start),
            TimeConditionPlan(f"{time_dimension.table}.{time_dimension.date_key_field}", "lte", end),
        )
    return TimePlan(
        dimension_id=time_dimension.id,
        table=time_dimension.table,
        grain=grain,
        start=start,
        end=end,
        conditions=conditions,
    )


def _resolve_join_path(
    config: MetaConfig,
    fact_table: str,
    required_tables: set[str],
) -> list[JoinPlan]:
    """从事实表到所有所需维度表选择配置允许的JOIN路径。

    ``relationships`` 来自 ``conf/meta_config.yaml``，每条关系提供源字段、
    目标字段、基数和启用状态。这里把关系视为无向图的边：表是节点，
    关系是边；从事实表开始使用 BFS，逐层探索到目标表的最短路径。
    
    - 只遍历 ``enabled`` 的关系，避免使用已停用的业务关联。
    - 对每个所需表收集最短路径；找不到路径时拒绝计划。
    - 如果存在多条同长度最短路径，说明语义关系存在歧义，拒绝计划，
      不把不确定的JOIN交给后续SQL编译器猜测。
    - 多个维度复用同一关系时按关系ID去重，最终输出稳定的JoinPlan列表。
    """
    if not required_tables:
        return []
    relationships = [relationship for relationship in config.relationships if relationship.enabled]
    adjacency: dict[str, list[RelationshipConfig]] = {}
    for relationship in relationships:
        source_table = relationship.source.split(".")[0]
        target_table = relationship.target.split(".")[0]
        adjacency.setdefault(source_table, []).append(relationship)
        adjacency.setdefault(target_table, []).append(relationship)

    selected: dict[str, RelationshipConfig] = {}
    # 每个维度、过滤条件和时间条件都会贡献一个所需物理表；从事实表
    # 出发为这些表解析关系路径，结果将直接供后续SQL编译生成JOIN子句。
    for required_table in required_tables:
        if required_table == fact_table:
            continue
        # BFS队列保存“当前所在表 + 已选择的关系路径”。先入队的路径
        # 层数更少，因此第一次到达目标表即可得到最短路径候选。
        queue = deque([(fact_table, [])])
        visited = {fact_table}
        paths: list[list[RelationshipConfig]] = []
        while queue:
            current, path = queue.popleft()
            if current == required_table:
                paths.append(path)
                continue
            # relationships 已按表构建邻接表；每次只沿配置声明的关系
            # 前进，不根据表名或字段名自行推断JOIN。
            for relationship in adjacency.get(current, []):
                source_table = relationship.source.split(".")[0]
                target_table = relationship.target.split(".")[0]
                next_table = target_table if source_table == current else source_table
                # 防止关系图存在环时反复绕圈，同时允许不同路径分别
                # 参与最短路径歧义判断。
                path_tables = {fact_table}
                for path_relationship in path:
                    path_tables.add(path_relationship.source.split(".")[0])
                    path_tables.add(path_relationship.target.split(".")[0])
                if next_table not in path_tables:
                    queue.append((next_table, path + [relationship]))
        if not paths:
            raise QueryPlanError(f"无法从事实表 {fact_table} 找到关系路径到 {required_table}")
        shortest_length = min(len(path) for path in paths)
        shortest = [path for path in paths if len(path) == shortest_length]
        if len(shortest) > 1:
            raise QueryPlanError(f"到 {required_table} 存在歧义关系路径")
        for relationship in shortest[0]:
            selected[relationship.id] = relationship

    return [
        JoinPlan(
            relationship_id=relationship.id,
            source=relationship.source,
            target=relationship.target,
            cardinality=relationship.cardinality,
        )
        for relationship in selected.values()
    ]


def _resolve_order_by(
    intent: QueryIntent,
    metrics: list[MetricPlan],
    dimensions: list[DimensionPlan],
) -> list[OrderPlan]:
    """校验排序字段只能引用当前计划已选中的指标或维度。"""
    available: dict[str, str] = {}
    for item in metrics + dimensions:
        for token in (item.id, item.name, *item.aliases):
            normalized = token.strip().casefold()
            if normalized in available and available[normalized] != item.id:
                raise QueryPlanError(f"排序字段存在歧义: {token}")
            available[normalized] = item.id
    result: list[OrderPlan] = []
    for item in intent.order_by:
        field = item.get("field")
        direction = item.get("direction")
        if not isinstance(field, str) or direction not in {"asc", "desc"}:
            raise QueryPlanError("排序条件必须包含合法field和direction")
        field_id = available.get(field.strip().casefold())
        if not field_id:
            raise QueryPlanError(f"排序字段未出现在当前查询计划中: {field}")
        result.append(OrderPlan(field_id=field_id, direction=direction))
    return result


def _aggregation_for(metric: MetricPlan) -> str:
    """从稳定指标ID生成受方案约束的聚合表达式。"""
    if metric.id == "order_count":
        return "COUNT(DISTINCT fact_order.order_id)"
    if metric.id == "average_quantity_per_order":
        return "SUM(fact_order.order_quantity) / NULLIF(COUNT(DISTINCT fact_order.order_id), 0)"
    if metric.expression:
        return metric.expression
    raise QueryPlanError(f"指标没有可用聚合定义: {metric.id}")


def _resolve_one(token: str, items: list[Any], aliases_getter, label: str):
    normalized = token.strip().casefold()
    matches = [item for item in items if normalized in {str(alias).strip().casefold() for alias in aliases_getter(item)}]
    if not matches:
        raise QueryPlanError(f"未知{label}: {token}")
    if len(matches) > 1:
        raise QueryPlanError(f"{label}存在歧义: {token}")
    return matches[0]


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().casefold()
        if normalized not in seen:
            seen.add(normalized)
            result.append(value)
    return result
