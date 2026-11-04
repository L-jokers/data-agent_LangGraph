from typing import Any, NotRequired, TypedDict

class DateInfoState(TypedDict):
    date: str
    weekday: str
    quarter: str


class DBInfoState(TypedDict):
    dialect: str
    version: str


class DataAgentState(TypedDict):
    query: str  # 用户查询
    semantic_version_id: NotRequired[str]
    # 阶段二新增：LLM解析后的结构化单轮查询意图。
    # 该字段承载指标、维度、过滤、时间表达式、排序和终态信息，后续阶段只消费结构化结果。
    query_intent: NotRequired[Any]
    semantic_candidates: NotRequired[dict[str, Any]]

    # 阶段二新增：由确定性时间解析器根据UTC+8参考时间计算出的绝对时间范围。
    # 意图澄清或不支持时该字段为None，且工作流不会进入SQL链路。
    resolved_time: NotRequired[dict[str, str] | None]

    # 阶段二新增：工作流终态，当前包括needs_clarification和unsupported。
    terminal_status: NotRequired[str]

    # 阶段三新增：由语义配置确定性生成并校验后的查询计划。
    # 计划只包含稳定ID、配置允许的关系路径、聚合和过滤约束，不包含LLM任意SQL。
    query_plan: NotRequired[Any]

    # 阶段四新增：确定性SQL编译结果，包含参数绑定和执行限制。
    compiled_query: NotRequired[Any]
    date_info: NotRequired[DateInfoState]  # 日期信息
    db_info: NotRequired[DBInfoState]  # 数据库信息

    sql: NotRequired[str]  # 生成的SQL

    error: NotRequired[str | None]  # 验证SQL时的错误信息
    correction_attempts: NotRequired[int]
    correction_events: NotRequired[list[str]]
    correction_eligible: NotRequired[bool]
