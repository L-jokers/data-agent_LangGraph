# Development Status

> 存档时间：2026-10-26
>
> 工作目录：`data-agent`
>
> 当前状态：阶段四验收通过，暂停开发，等待后续明确指令。

## 已完成阶段

### 阶段 0：现状与基线整理

- 已完成方案、代码、配置、Docker 文件和测试入口的只读分析。
- 已确认本期范围为单轮查询，多轮会话不在当前实现范围内。
- 已确认 MySQL、Qdrant、Elasticsearch 的清理边界。

### 阶段 1：语义配置与元数据构建

- 语义配置已覆盖：`model`、`tables`、`datasets`、`relationships`、`dimensions`、`time_dimensions`、`metrics`。
- 已实现配置静态校验和配置与数仓 schema 的校验入口。
- 已扩展元数据模型、Mapper、Repository 和 MySQL 元数据 DDL。
- 已落实指标口径：
  - `paid_amount`
  - `product_quantity`
  - `order_count`
  - `average_quantity_per_order`
- `AOV` 仅作为平均每单购买件数的项目别名。
- `GMV` 不作为订单实付金额自动别名。

### 阶段 2：结构化查询意图和时间解析

- 已增加结构化查询意图模型和 JSON 输出解析。
- 已实现 UTC+8 确定性时间解析。
- 已支持今天、昨天、前天、本月、上个月、最近 N 天、显式年月和日期范围。
- 用户只提供月份但缺少年份时进入 `needs_clarification`。
- 不支持的时间表达式进入 `unsupported`。
- 澄清和不支持终态在召回、SQL 编译和执行前终止。
- 支持通过 `reference_time` 注入固定测试参考时间。

### 阶段 3：查询规划与语义校验

- 已实现 `QueryPlan`、指标/维度/过滤/时间/排序/limit/聚合计划对象。
- 规划器按语义配置中的稳定 ID、规范名称和别名解析意图。
- JOIN 路径由配置中的启用关系通过 BFS 选择。
- 无路径、最短路径歧义、未知对象、非法过滤、非法排序和 limit 越界会阻断计划。
- 月份计划同时生成年份和月份条件。
- `order_count` 使用 `COUNT(DISTINCT fact_order.order_id)`。
- 平均每单购买件数使用当前分组范围内的购买数量除以去重订单数。

### 阶段 4：确定性 SQL 编译、安全和执行限制

- 已新增确定性 MySQL 8 SQL 编译器，基于有效查询计划生成 SQL。
- 用户过滤值使用参数绑定，不拼接到 SQL 文本。
- 表、字段、JOIN、函数和指标表达式受白名单约束。
- 自动生成 `LIMIT`，并支持 `MAX_EXECUTION_TIME` hint。
- 已使用 SQLGlot MySQL AST 做独立安全校验。
- 已拒绝 DML、DDL、多语句、白名单外表/字段/函数/JOIN、通配字段和未绑定过滤值。
- 已实现应用层查询超时和结果行数检测/截断元信息。
- 已移除工作流中的 `correct_sql → execute_sql` 直通路径。
- SQL 编译或安全校验失败不会自动交给 LLM 改写后执行。
- 数据库执行错误对外转换为稳定错误类别，避免泄露内部细节。
- 已加入 `sqlglot>=27.0.0,<28`，锁定版本为 `27.29.0`。

## 当前已修改文件

以下列表根据当前 `git status --short` 和实际工作区核对整理。除特别说明外，均为本开发会话产生或修改的阶段实现文件。

### 已修改的跟踪文件

- `app/agent/context.py`
- `app/agent/graph.py`
- `app/agent/nodes/correct_sql.py`
- `app/agent/nodes/execute_sql.py`
- `app/agent/nodes/generate_sql.py`
- `app/agent/nodes/validate_sql.py`
- `app/agent/state.py`
- `app/conf/meta_config.py`
- `app/entities/metric_info.py`
- `app/models/metric_info_mysql.py`
- `app/repositories/mysql/dw/dw_mysql_repository.py`
- `app/repositories/mysql/meta/mappers/metric_info_mapper.py`
- `app/repositories/mysql/meta/meta_mysql_repository.py`
- `app/services/meta_knowledge_service.py`
- `conf/meta_config.yaml`
- `docker/mysql/meta.sql`
- `pyproject.toml`
- `uv.lock`

### 当前新增的未跟踪文件

- `app/agent/nodes/intent_terminal.py`
- `app/agent/nodes/parse_intent.py`
- `app/agent/nodes/plan_query.py`
- `app/agent/nodes/resolve_time.py`
- `app/compiler/__init__.py`
- `app/compiler/sql_compiler.py`
- `app/entities/dataset_info.py`
- `app/entities/relationship_info.py`
- `app/entities/time_dimension_info.py`
- `app/intent/__init__.py`
- `app/intent/llm_output.py`
- `app/intent/models.py`
- `app/models/dataset_info_mysql.py`
- `app/models/relationship_info_mysql.py`
- `app/models/time_dimension_info_mysql.py`
- `app/planner/__init__.py`
- `app/planner/models.py`
- `app/planner/planner.py`
- `app/repositories/mysql/meta/mappers/dataset_info_mapper.py`
- `app/repositories/mysql/meta/mappers/relationship_info_mapper.py`
- `app/repositories/mysql/meta/mappers/time_dimension_info_mapper.py`
- `app/security/__init__.py`
- `app/security/query_limits.py`
- `app/security/sqlglot_validator.py`
- `app/time/__init__.py`
- `app/time/parser.py`
- `prompts/parse_intent.prompt`
- `tests/test_intent_and_time.py`
- `tests/test_meta_config.py`
- `tests/test_query_planner.py`
- `tests/test_sql_phase4.py`

### 已存在但未纳入本次处理的未跟踪文件

- `改造开发落地提示词.md`

该文件在阶段一开始已经处于未跟踪状态，本次未修改其内容。

## 测试命令和结果

最近一次核实执行于 2026-10-26：

```text
uv run python -m compileall -q app tests
uv run python -m unittest discover -s tests -v
uv run python -c "import app.agent.graph; print('graph import ok')"
git diff --check
```

结果：

- Python 编译检查通过。
- 全量单元测试 `33` 项通过。
- 阶段一、阶段二、阶段三和阶段四测试均通过。
- LangGraph 导入检查通过，输出 `graph import ok`。
- `git diff --check` 通过；仅有工作区换行符格式提示，无 diff 错误。

阶段四测试覆盖：

- SQL 编译结构和 MySQL 方言。
- 参数绑定和注入值隔离。
- SQLGlot AST 正常查询校验。
- INSERT、UPDATE、DELETE、DROP、ALTER、CREATE、TRUNCATE 拒绝。
- 多语句拒绝。
- 未授权表、字段、通配字段、函数和 JOIN 条件拒绝。
- `MAX_EXECUTION_TIME` 和 `LIMIT` 检查。
- 结果截断及截断元信息。
- 应用层超时。
- 数据库错误对外脱敏。

## 未完成事项

- 阶段五固定回归验收和 API/SSE 全链路测试尚未开始。
- 阶段六未来多轮能力尚未实现，且按当前方案明确不属于本期实现范围。
- 尚未在真实 MySQL 样本库上执行确定性 SQL 集成测试。
- 尚未用独立核对 SQL 验证真实查询结果。
- 尚未在真实 Qdrant/Elasticsearch 环境验证阶段一派生索引一致性。
- 尚未实现扫描量精确限制。
- 尚未实现多轮会话、`session_id`、持久化查询状态和并发会话管理。
- 尚未实现通用指标表达式编译；当前编译器严格支持本期确认的四个指标表达式。
- 尚未实现有限自动 SQL 修正；当前自动修正已禁用。
- API/SSE 契约的完整 `sql`、`done`、`clarification`、`unsupported` 集成验收尚未完成。
- 尚未执行元数据库、Qdrant collection 或 ES index 的清理/重建。
- 尚未执行 `git commit`。

## 后续开发阶段

### 阶段五：API/SSE 契约和回归验收

**状态：未开始，等待明确开发指令。**

**目标：**

- 在不改变 `POST /api/query` 基本请求格式的前提下，规范 SSE 事件和终态。

**预计改动文件/模块：**

- `app/api/schemas/query_schema.py`
- `app/api/routers/query_router.py`
- `app/services/query_service.py`
- 新增 `tests/api/`
- 新增 `tests/integration/`
- 新增 `tests/security/`
- 新增 `tests/fixtures/`
- `README.md`

**SSE 事件顺序：**

```text
progress
→ sql
→ result / clarification / error
→ done
```

**终态：**

- `success`
- `needs_clarification`
- `unsupported`
- `error`

**阶段五约束：**

- 不暴露候选评分。
- 不暴露数据库堆栈。
- 不暴露连接串、密码或 API Key。
- SQL 事件按需要脱敏参数。
- 空结果使用 `done.status = success` 和 `result.rows = []`，并明确表示不是不支持。
- 不实现多轮会话，不加入 `session_id`。
- 不改变已确认指标口径。
- 不在未确认目标环境前清理或重建 MySQL、Qdrant、ES。

**阶段五测试和验收：**

- 原请求格式兼容：

  ```json
  {"query":"查询 2025 年 1 月各大区的订单实付金额"}
  ```

- 事件顺序测试。
- 成功终态测试。
- 澄清终态测试。
- 不支持终态测试。
- 安全错误终态测试。
- 空结果成功测试。
- 结果截断元信息测试。
- 错误脱敏测试。

### 阶段六：正式回归验收

**状态：未开始；必须在阶段五完成后执行，不纳入多轮实现。**

**目标：**

- 按照方案固定案例验收完整单轮链路。

**预计改动文件/模块：**

- `tests/`
- `tests/fixtures/`
- `README.md`
- 可选新增回归报告文件。

**本期必须通过：**

1. 案例一：2025 年 1 月各大区的订单实付金额和商品购买数量，按实付金额降序。
2. 四个正式指标分别单独查询。
3. 多指标合理组合。
4. 地区、商品、客户、时间维度组合。
5. AOV 正确归一化为平均每单购买件数。
6. GMV 不自动映射。
7. 缺少年份时澄清。
8. 不支持时间表达式返回 `unsupported`。
9. 空结果返回成功。
10. 非只读 SQL 被拒绝。
11. 白名单外对象被拒绝。
12. 案例二、三继续标注为本期未实现，不阻塞单轮验收。

**正式回归记录要求：**

- 每个基准问题记录自然语言问题、预期意图、查询计划、SQL 关键约束、核对 SQL/结果和预期终态。
- 失败案例记录原因和修复，不通过扩大自由 Prompt 掩盖语义问题。

**阶段六不实现：**

- 不实现多轮会话。
- 不实现 `session_id`、持久化查询状态或案例二、三的多轮继承语义。

## 已知风险

- 当前工作区包含阶段一至阶段四的累计修改，尚未形成 Git commit；恢复工作时必须以本文件和 `git status`/`git diff` 为准。
- 当前配置和 Docker 文件中仍可能存在明文数据库密码或 API Key；按既定决策暂不在本阶段改动，但提交 Git 前必须替换并轮换真实凭据。
- 元数据 DDL 文件包含初始化脚本中的 `DROP TABLE IF EXISTS`；本次未执行该脚本，后续执行前必须确认目标仅为开发环境 `meta` 数据库。
- SQL 编译器的扫描量精确限制未实现，不能将 `MAX_EXECUTION_TIME`、`LIMIT` 或应用层超时视为扫描量限制的替代品。
- 当前测试主要是纯内存单元测试和 FakeSession 测试，尚未证明 MySQL 8 驱动、参数绑定和真实执行计划行为完全一致。
- SQLGlot 版本已锁定为 `27.29.0`；升级 SQLGlot 时需要重新核验 AST 节点类型和安全规则。
- 当前查询结果截断依赖应用层多取一行；大结果集的数据库扫描成本仍可能较高。
- 当前 `MAX_EXECUTION_TIME` 使用 MySQL hint，实际效果需要在目标 MySQL 8 环境验证。
- API/SSE 文件保持原有契约，阶段四尚未完成最终对外事件顺序和终态回归验收。

## 禁止事项

在收到新的明确开发指令前，禁止：

- 开始阶段五或任何下一阶段编码。
- 修改 API/SSE 契约。
- 修改或扩展多轮会话状态。
- 清空、删除、重建或覆盖任何 MySQL 数据库、表或用户数据。
- 默认清理或重建 `dw` 数据库。
- 清理、删除或重建未明确指定的 Qdrant collection。
- 清理、删除或重建未明确指定的 Elasticsearch index。
- 删除或重建 Docker volume：`mysql_data`、`es_data`、`qdrant_data`。
- 执行生产或非明确开发环境资源操作。
- 执行 `git commit`、创建分支或重置用户已有修改。
- 将 SQL 扫描量限制描述为已实现。

## 下一步唯一任务

**等待用户恢复开发并明确指定阶段五“回归验收”的开发指令；在此之前保持暂停，不修改代码、不运行数据资源操作。**

## 阶段五实施更新（2026-10-26）

- 阶段五“API/SSE 契约和回归验收”已实现，尚未进行用户最终验收。
- `POST /api/query` 继续接受 `{ "query": "..." }`，并返回 `text/event-stream`。
- SSE 顺序收口为 `progress → sql → result/clarification/unsupported/error → done`；澄清、不支持和安全错误不会执行 SQL。
- 成功结果使用 `result.rows`；空结果仍为 `done.status=success`，并带有 `empty` 与说明信息；截断结果返回 `truncated`、`row_count`、`max_rows`。
- 统一脱敏数据库/内部异常，不返回候选评分、堆栈、连接串、密码或 API Key；SQL 事件不发送绑定参数。
- 新增测试：`tests/api/test_query_api_contract.py`、`tests/security/test_sse_security.py`。
- 阶段五测试结果：完整测试集 `33` 项通过；编译检查通过；`git diff --check` 通过。

## 当前未完成阶段

### 阶段六：正式回归验收

- 尚未开始，必须在阶段五最终验收后执行。
- 验证固定案例、四项正式指标、组合维度、AOV、GMV、缺少年份澄清、不支持时间、空结果、非只读 SQL 和白名单拒绝。
- 不实现多轮查询、`session_id` 或持久化会话状态。

## 当前唯一下一步任务

等待用户验收阶段五并明确下达阶段六正式回归验收指令；在此之前不开始阶段六，不实现多轮查询，不清理或重建任何数据库、Qdrant collection、Elasticsearch index 或 Docker volume，不执行 `git commit`。

## 阶段六实施更新（2026-10-26）

- 阶段六单轮正式回归验收已完成，等待用户最终验收。
- 已在真实 MySQL 8、FastAPI/SSE、Elasticsearch、Qdrant、Embedding 服务环境完成连通性或链路验证。
- 真实 MySQL 核对结果：2025 年 1 月订单实付金额 `109030.5`，商品购买数量 `149`，订单数 `40`，平均每单购买件数 `3.7250`。
- 案例一真实 SSE 返回 5 个大区结果，按实付金额降序；缺少年份、不支持时间、GMV 和空结果语义均符合要求。
- 阶段六完整测试集共 `41` 项通过；新增验收记录见 `STAGE6_REGRESSION_REPORT.md`。
- 结果截断修复：`QueryPlan.limit_explicit` 保留用户是否显式指定 LIMIT；SQL 编译器在未指定或超过系统上限时生成 `max_rows + 1`，从而使应用层多读一行并可靠返回 `truncated`。
- Qdrant/ES 服务和资源存在，但当前阈值检索未返回命中，已记录为辅助召回质量风险；确定性语义链路未受影响。

## 阶段六后的未完成事项

- 案例二、案例三多轮查询仍未实现，且不阻塞本期单轮验收。
- 精确扫描量限制仍未实现。
- Qdrant/ES 辅助召回阈值和数据质量需要后续专项调查。
- 提交 Git 前仍需替换并轮换配置中的真实凭据。

## 当前唯一下一步任务

等待用户对阶段六正式回归结果进行最终验收；在此之前不开始多轮查询，不执行任何数据库、Qdrant collection、Elasticsearch index 或 Docker volume 的清理/重建，不执行 `git commit`。
