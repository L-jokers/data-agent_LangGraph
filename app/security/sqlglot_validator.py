from typing import Any

from sqlglot import exp, parse

from app.compiler.sql_compiler import CompiledQuery


class SQLSecurityError(ValueError):
    pass


def validate_compiled_query(
    compiled: CompiledQuery,
    *,
    snapshot: Any | None = None,
    plan: Any | None = None,
) -> None:
    """使用SQLGlot MySQL AST对编译结果做独立只读和白名单校验。"""
    try:
        statements = parse(compiled.sql, read="mysql")
    except Exception as exc:
        raise SQLSecurityError("SQL AST解析失败") from exc
    if len(statements) != 1:
        raise SQLSecurityError("禁止多语句SQL")
    statement = statements[0]
    if not isinstance(statement, exp.Select):
        raise SQLSecurityError("只允许单条SELECT查询")
    if statement.find(exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.TruncateTable):
        raise SQLSecurityError("检测到不允许的DML或DDL操作")

    tables = {table.name for table in statement.find_all(exp.Table)}
    if not tables:
        raise SQLSecurityError("查询必须包含语义模型允许的表")
    if not tables.issubset(compiled.allowed_tables):
        raise SQLSecurityError("存在白名单外的表")
    if snapshot is not None:
        _validate_snapshot_objects(compiled, snapshot)

    allowed_columns = {value.split(".")[-1] for value in compiled.allowed_columns}
    if statement.find(exp.Star):
        raise SQLSecurityError("禁止使用未展开的通配字段")
    for column in statement.find_all(exp.Column):
        if column.name not in allowed_columns:
            raise SQLSecurityError("存在白名单外的字段")

    for function in statement.find_all(exp.Func):
        function_name = (function.name or function.sql_name()).upper()
        if function_name in {"AND", "OR"}:
            continue
        if function_name not in compiled.allowed_functions:
            raise SQLSecurityError(f"存在白名单外的函数: {function_name}")

    _validate_windows(statement)
    limit = statement.args.get("limit")
    if limit is None or not isinstance(limit.expression, exp.Literal) or not limit.expression.is_number:
        raise SQLSecurityError("LIMIT必须是确定的数值")
    limit_value = int(limit.expression.this)
    if limit_value <= 0 or limit_value > compiled.max_rows + 1:
        raise SQLSecurityError("LIMIT超出查询资源边界")
    if plan is not None and getattr(plan, "limit_explicit", False):
        expected = min(plan.limit, compiled.max_rows) if plan.limit <= compiled.max_rows else compiled.max_rows + 1
        if limit_value != expected:
            raise SQLSecurityError("LIMIT与查询计划不一致")

    joins = list(statement.find_all(exp.Join))
    if len(joins) != len(compiled.allowed_joins):
        raise SQLSecurityError("JOIN数量与查询计划不一致")
    for join in joins:
        condition = join.args.get("on")
        if condition is None:
            raise SQLSecurityError("JOIN缺少配置关系条件")
        if condition.sql(dialect="mysql") not in compiled.allowed_join_conditions:
            raise SQLSecurityError("JOIN条件不在语义关系白名单中")

    where = statement.args.get("where")
    for where_literal in where.find_all(exp.Literal) if where else []:
        if where_literal.is_string or where_literal.is_number:
            raise SQLSecurityError("过滤值必须使用参数绑定")
    placeholders = {placeholder.name for placeholder in statement.find_all(exp.Placeholder)}
    if placeholders != set(compiled.params):
        raise SQLSecurityError("SQL参数与绑定参数不一致")


def _validate_snapshot_objects(compiled: CompiledQuery, snapshot: Any) -> None:
    table_names = {item.name for item in snapshot.tables}
    declared_columns = {
        f"{table.name}.{column.name}"
        for table in snapshot.tables
        for column in snapshot.columns
        if column.table_id == table.id
    }
    physical_tables = {value for value in compiled.allowed_tables if "." not in value}
    if not physical_tables.issubset(table_names):
        raise SQLSecurityError("编译计划包含快照外的表")
    physical_columns = {value for value in compiled.allowed_columns if "." in value}
    if not physical_columns.issubset(declared_columns):
        raise SQLSecurityError("编译计划包含快照外的字段")


def _validate_windows(statement: exp.Expression) -> None:
    where = statement.args.get("where")
    if where is not None and where.find(exp.Window):
        raise SQLSecurityError("窗口函数禁止出现在WHERE")
    group = statement.args.get("group")
    if group is not None and group.find(exp.Window):
        raise SQLSecurityError("窗口函数禁止出现在GROUP BY")
    for join in statement.find_all(exp.Join):
        condition = join.args.get("on")
        if condition is not None and condition.find(exp.Window):
            raise SQLSecurityError("窗口函数禁止出现在JOIN ON")
    for window in statement.find_all(exp.Window):
        if window.parent and not isinstance(window.parent, (exp.Alias, exp.Select)):
            raise SQLSecurityError("窗口函数只能作为最终SELECT输出")
