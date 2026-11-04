from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


class ExpressionASTError(ValueError):
    pass


SUPPORTED_AGGREGATES = {"sum", "count", "count_distinct", "avg", "min", "max"}
SUPPORTED_FUNCTIONS = {"nullif", "coalesce", "abs", "round"}
SUPPORTED_OPERATORS = {"+", "-", "*", "/", "=", "!=", ">", ">=", "<", "<="}
SUPPORTED_WINDOW_FUNCTIONS = {"row_number", "rank", "dense_rank", "sum", "avg", "count"}
SUPPORTED_FRAMES = {None, "rows_unbounded_preceding", "rows_unbounded_preceding_to_current"}


@dataclass
class ExpressionCompileContext:
    allowed_columns: set[str]
    allowed_tables: set[str]
    allowed_functions: set[str] = field(default_factory=set)
    metric_asts: dict[str, dict[str, Any]] = field(default_factory=dict)
    compiling_metrics: set[str] = field(default_factory=set)


def compile_metric_ast(metric_id: str, ast: dict[str, Any], context: ExpressionCompileContext) -> str:
    if metric_id in context.compiling_metrics:
        raise ExpressionASTError(f"指标表达式存在循环依赖: {metric_id}")
    context.compiling_metrics.add(metric_id)
    try:
        return _compile(ast, context, top_level=True, location="select")
    finally:
        context.compiling_metrics.remove(metric_id)


def _compile(node: Any, context: ExpressionCompileContext, *, top_level: bool, location: str) -> str:
    if not isinstance(node, dict) or set(node) - {"node", "ref", "id", "function", "args", "input", "op", "left", "right", "when", "then", "else", "condition", "value", "partition_by", "order_by", "frame", "direction"}:
        raise ExpressionASTError("AST包含未知字段或节点格式错误")
    node_type = node.get("node")
    if not isinstance(node_type, str):
        raise ExpressionASTError("AST节点缺少node")
    if node_type == "field":
        reference = node.get("ref")
        if not isinstance(reference, str) or reference not in context.allowed_columns:
            raise ExpressionASTError(f"字段不在语义白名单: {reference}")
        table, column = _split_reference(reference)
        context.allowed_tables.add(table)
        return f"`{table}`.`{column}`"
    if node_type == "metric_ref":
        metric_id = node.get("id")
        if not isinstance(metric_id, str) or metric_id not in context.metric_asts:
            raise ExpressionASTError(f"未知指标依赖: {metric_id}")
        return compile_metric_ast(metric_id, context.metric_asts[metric_id], context)
    if node_type == "literal":
        value = node.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value not in {0, 1}:
            raise ExpressionASTError("只允许声明的数值常量0或1")
        return str(value)
    if node_type == "aggregate":
        function = node.get("function")
        if function not in SUPPORTED_AGGREGATES:
            raise ExpressionASTError(f"不支持的聚合函数: {function}")
        if location in {"where", "group_by", "join_on", "window"}:
            raise ExpressionASTError("聚合表达式位置不安全")
        value = _compile(node.get("input"), context, top_level=False, location="aggregate")
        context.allowed_functions.add("COUNT" if function == "count_distinct" else function.upper())
        function_sql = "COUNT(DISTINCT" if function == "count_distinct" else function.upper()
        if function == "count_distinct":
            return f"{function_sql} {value})"
        return f"{function_sql}({value})"
    if node_type == "function":
        function = node.get("function")
        if function not in SUPPORTED_FUNCTIONS:
            raise ExpressionASTError(f"不支持的函数: {function}")
        args = node.get("args")
        if not isinstance(args, list) or not args:
            raise ExpressionASTError("函数参数必须为非空数组")
        compiled = [_compile(item, context, top_level=False, location=location) for item in args]
        context.allowed_functions.add(function.upper())
        return f"{function.upper()}({', '.join(compiled)})"
    if node_type == "binary":
        operator = node.get("op")
        if operator not in SUPPORTED_OPERATORS:
            raise ExpressionASTError(f"不支持的表达式算子: {operator}")
        left = _compile(node.get("left"), context, top_level=False, location=location)
        right = _compile(node.get("right"), context, top_level=False, location=location)
        return f"({left} {operator} {right})"
    if node_type == "case":
        when = node.get("when")
        then = node.get("then")
        otherwise = node.get("else")
        if not isinstance(when, dict) or then is None or otherwise is None:
            raise ExpressionASTError("CASE必须包含when、then、else")
        condition = _compile(when, context, top_level=False, location="case_when")
        return f"CASE WHEN {condition} THEN {_compile(then, context, top_level=False, location=location)} ELSE {_compile(otherwise, context, top_level=False, location=location)} END"
    if node_type == "condition_aggregate":
        function = node.get("function")
        if function not in SUPPORTED_AGGREGATES:
            raise ExpressionASTError(f"不支持的条件聚合函数: {function}")
        condition = _compile(node.get("condition"), context, top_level=False, location="where")
        value = _compile(node.get("input"), context, top_level=False, location="aggregate")
        return f"{function.upper()}(CASE WHEN {condition} THEN {value} ELSE 0 END)"
    if node_type == "window":
        if not top_level or location != "select":
            raise ExpressionASTError("窗口函数只能作为最终SELECT输出")
        function = node.get("function")
        if function not in SUPPORTED_WINDOW_FUNCTIONS:
            raise ExpressionASTError(f"不支持的窗口函数: {function}")
        frame = node.get("frame")
        if frame not in SUPPORTED_FRAMES:
            raise ExpressionASTError("窗口frame不在批准清单")
        partition = [_compile(item, context, top_level=False, location="window") for item in node.get("partition_by", [])]
        order = []
        for item in node.get("order_by", []):
            if not isinstance(item, dict) or item.get("direction", "asc") not in {"asc", "desc"}:
                raise ExpressionASTError("窗口ORDER BY格式非法")
            order.append(f"{_compile(item.get('expr'), context, top_level=False, location='window')} {item.get('direction', 'asc').upper()}")
        inner = node.get("input")
        context.allowed_functions.add(function.upper())
        if function in {"sum", "avg", "count"}:
            inner_sql = _compile(inner, context, top_level=False, location="window")
            expression = f"{function.upper()}({inner_sql})"
        else:
            expression = f"{function.upper()}()"
        clauses = []
        if partition:
            clauses.append("PARTITION BY " + ", ".join(partition))
        if order:
            clauses.append("ORDER BY " + ", ".join(order))
        if frame == "rows_unbounded_preceding_to_current":
            clauses.append("ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW")
        elif frame == "rows_unbounded_preceding":
            clauses.append("ROWS UNBOUNDED PRECEDING")
        return f"{expression} OVER ({' '.join(clauses)})"
    raise ExpressionASTError(f"不支持的AST节点: {node_type}")


def _split_reference(reference: str) -> tuple[str, str]:
    parts = reference.split(".")
    if len(parts) != 2 or not all(parts):
        raise ExpressionASTError(f"字段引用格式非法: {reference}")
    return parts[0], parts[1]


def legacy_expression_to_ast(expression: str) -> dict[str, Any]:
    """仅为旧 QueryPlan 测试/迁移提供语法受限转换，不接受任意 SQL。"""
    match = re.fullmatch(r"(SUM|AVG|MIN|MAX)\(([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\)", expression or "")
    if match:
        return {"node": "aggregate", "function": match.group(1).lower(), "input": {"node": "field", "ref": f"{match.group(2)}.{match.group(3)}"}}
    match = re.fullmatch(r"COUNT\(DISTINCT ([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\)", expression or "")
    if match:
        return {"node": "aggregate", "function": "count_distinct", "input": {"node": "field", "ref": f"{match.group(1)}.{match.group(2)}"}}
    raise ExpressionASTError("旧表达式无法安全迁移为JSON AST")
