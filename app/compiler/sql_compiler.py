from dataclasses import dataclass
from typing import Any

from app.planner.models import QueryPlan, QueryPlanError


class SQLCompilerError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    params: dict[str, Any]
    max_rows: int
    timeout_seconds: float
    max_execution_time_ms: int
    allowed_tables: frozenset[str]
    allowed_columns: frozenset[str]
    allowed_functions: frozenset[str]
    allowed_joins: frozenset[str]
    allowed_join_conditions: frozenset[str]


def compile_query(
    plan: QueryPlan,
    *,
    max_rows: int = 100,
    timeout_seconds: float = 10.0,
    max_execution_time_ms: int = 5000,
) -> CompiledQuery:
    """将已校验的QueryPlan编译为MySQL 8参数化查询。

    表名、列名、JOIN和聚合表达式都来自QueryPlan；用户提供的过滤值只
    进入params，绝不拼接到SQL文本中。
    """
    if max_rows <= 0 or timeout_seconds <= 0 or max_execution_time_ms <= 0:
        raise SQLCompilerError("查询资源限制必须为正数")
    if not plan.metrics:
        raise SQLCompilerError("查询计划没有指标")

    select_parts: list[str] = []
    allowed_tables = {plan.fact_table}
    allowed_columns: set[str] = set()
    allowed_functions: set[str] = {"SUM", "COUNT", "NULLIF", "MAX_EXECUTION_TIME"}
    allowed_joins: set[str] = set()
    allowed_join_conditions: set[str] = set()

    for dimension in plan.dimensions:
        allowed_tables.add(dimension.table)
        allowed_columns.add(f"{dimension.table}.{dimension.column}")
        allowed_columns.add(dimension.id)
        select_parts.append(
            f"{_quote(dimension.table)}.{_quote(dimension.column)} AS {_quote(dimension.id)}"
        )

    for metric in plan.metrics:
        expression = plan.aggregations.get(metric.id)
        if not expression:
            raise SQLCompilerError(f"指标缺少聚合定义: {metric.id}")
        select_parts.append(f"{_compile_expression(expression, allowed_columns, allowed_tables)} AS {_quote(metric.id)}")
        allowed_columns.add(metric.id)
        if metric.id == "order_count":
            allowed_columns.add("fact_order.order_id")
        elif metric.id == "paid_amount":
            allowed_columns.add("fact_order.order_amount")
        elif metric.id == "product_quantity":
            allowed_columns.add("fact_order.order_quantity")
        elif metric.id == "average_quantity_per_order":
            allowed_columns.update({"fact_order.order_quantity", "fact_order.order_id"})

    join_parts: list[str] = []
    joined_tables = {plan.fact_table}
    for join in plan.joins:
        source_table, source_column = _split_reference(join.source)
        target_table, target_column = _split_reference(join.target)
        if source_table in joined_tables and target_table not in joined_tables:
            left, right, join_table = join.source, join.target, target_table
        elif target_table in joined_tables and source_table not in joined_tables:
            left, right, join_table = join.target, join.source, source_table
        else:
            raise SQLCompilerError(f"JOIN路径无法按计划展开: {join.relationship_id}")
        join_parts.append(
            f"JOIN {_quote(join_table)} ON {_qualified(left)} = {_qualified(right)}"
        )
        joined_tables.add(join_table)
        allowed_tables.update({source_table, target_table})
        allowed_columns.update({join.source, join.target})
        allowed_joins.add(join.relationship_id)
        allowed_join_conditions.add(
            _join_condition(join.source, join.target)
        )

    where_parts: list[str] = []
    params: dict[str, Any] = {}
    parameter_index = 0
    for filter_plan in plan.filters:
        allowed_tables.add(filter_plan.table)
        allowed_columns.add(f"{filter_plan.table}.{filter_plan.column}")
        if filter_plan.operator == "in":
            values = filter_plan.value if isinstance(filter_plan.value, (list, tuple, set)) else [filter_plan.value]
            if not values:
                raise SQLCompilerError("IN过滤条件不能为空")
            placeholders = []
            for value in values:
                placeholder = f"p{parameter_index}"
                parameter_index += 1
                placeholders.append(f":{placeholder}")
                params[placeholder] = value
            where_parts.append(
                f"{_quote(filter_plan.table)}.{_quote(filter_plan.column)} IN ({', '.join(placeholders)})"
            )
            continue
        placeholder = f"p{parameter_index}"
        parameter_index += 1
        where_parts.append(_filter_sql(filter_plan.table, filter_plan.column, filter_plan.operator, placeholder))
        params[placeholder] = f"%{filter_plan.value}%" if filter_plan.operator == "contains" else filter_plan.value

    if plan.time:
        allowed_tables.add(plan.time.table)
        for condition in plan.time.conditions:
            table, column = _split_reference(condition.field)
            allowed_columns.add(condition.field)
            placeholder = f"p{parameter_index}"
            parameter_index += 1
            where_parts.append(_filter_sql(table, column, condition.operator, placeholder))
            params[placeholder] = condition.value

    sql = (
        f"SELECT /*+ MAX_EXECUTION_TIME({max_execution_time_ms}) */ "
        + ", ".join(select_parts)
        + f" FROM {_quote(plan.fact_table)}"
        + (" " + " ".join(join_parts) if join_parts else "")
        + (" WHERE " + " AND ".join(where_parts) if where_parts else "")
    )
    if plan.dimensions:
        group_by = ", ".join(
            f"{_quote(dimension.table)}.{_quote(dimension.column)}"
            for dimension in plan.dimensions
        )
        sql += f" GROUP BY {group_by}"
    if plan.order_by:
        order_items = []
        for order in plan.order_by:
            order_items.append(f"{_quote(order.field_id)} {order.direction.upper()}")
        sql += " ORDER BY " + ", ".join(order_items)
    # 未显式给出 LIMIT 时，以及用户 LIMIT 超过系统上限时，多请求一行，
    # 让执行层能够判断真实结果是否超过 max_rows；用户较小的 LIMIT 则按其请求返回。
    sql_limit = plan.limit if plan.limit_explicit and plan.limit <= max_rows else max_rows + 1
    sql += f" LIMIT {sql_limit}"

    return CompiledQuery(
        sql=sql,
        params=params,
        max_rows=max_rows,
        timeout_seconds=timeout_seconds,
        max_execution_time_ms=max_execution_time_ms,
        allowed_tables=frozenset(allowed_tables),
        allowed_columns=frozenset(allowed_columns),
        allowed_functions=frozenset(allowed_functions),
        allowed_joins=frozenset(allowed_joins),
        allowed_join_conditions=frozenset(allowed_join_conditions),
    )


def _compile_expression(expression: str, allowed_columns: set[str], allowed_tables: set[str]) -> str:
    # 表达式来自已经通过阶段一静态校验的语义配置；这里仍只允许本期
    # 已确认的四个指标表达式，避免将任意配置文本当作SQL执行。
    allowed = {
        "SUM(fact_order.order_amount)": "SUM(fact_order.order_amount)",
        "SUM(fact_order.order_quantity)": "SUM(fact_order.order_quantity)",
        "COUNT(DISTINCT fact_order.order_id)": "COUNT(DISTINCT fact_order.order_id)",
        "SUM(fact_order.order_quantity) / NULLIF(COUNT(DISTINCT fact_order.order_id), 0)": (
            "SUM(fact_order.order_quantity) / NULLIF(COUNT(DISTINCT fact_order.order_id), 0)"
        ),
    }
    if expression not in allowed:
        raise SQLCompilerError(f"不允许的指标表达式: {expression}")
    for reference in ("fact_order.order_amount", "fact_order.order_quantity", "fact_order.order_id"):
        if reference in expression:
            allowed_tables.add(reference.split(".")[0])
            allowed_columns.add(reference)
    return allowed[expression]


def _filter_sql(table: str, column: str, operator: str, placeholder: str) -> str:
    field = f"{_quote(table)}.{_quote(column)}"
    if operator == "eq":
        return f"{field} = :{placeholder}"
    if operator == "gte":
        return f"{field} >= :{placeholder}"
    if operator == "lte":
        return f"{field} <= :{placeholder}"
    if operator == "contains":
        return f"{field} LIKE :{placeholder}"
    raise SQLCompilerError(f"不支持的过滤操作符: {operator}")


def _split_reference(reference: str) -> tuple[str, str]:
    parts = reference.split(".")
    if len(parts) != 2 or not all(parts):
        raise SQLCompilerError(f"非法字段引用: {reference}")
    return parts[0], parts[1]


def _qualified(reference: str) -> str:
    table, column = _split_reference(reference)
    return f"{_quote(table)}.{_quote(column)}"


def _join_condition(source: str, target: str) -> str:
    return f"{_qualified(source)} = {_qualified(target)}"


def _quote(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum() or identifier[0].isdigit():
        raise SQLCompilerError(f"非法SQL标识符: {identifier}")
    return f"`{identifier}`"
