# 阶段六正式回归与最终自审报告

> 对照文件：`智能问数系统改造技术开发方案.md`
>
> 自审日期：2026-10-26
>
> 范围：阶段 0～5 已完成实现、阶段六单轮正式回归；多轮查询明确不属于本期。

## 1. 结论摘要

本次实现已覆盖方案确定的单轮查询主链路：语义配置、元数据构建、结构化意图、UTC+8 时间解析、确定性规划、SQL 编译、SQLGlot 安全校验、执行限制和 API/SSE 终态。阶段六在真实 MySQL 8、FastAPI/SSE、Elasticsearch、Qdrant、Embedding 环境完成了可执行范围内的验证。

**结论：单轮正式回归通过，但不是“所有方案能力无条件完成”。** 下列事项仍是部分实现或明确不在本期范围：多轮会话、精确扫描量限制、Qdrant/ES 召回质量、复杂自然语言的完整 LLM 覆盖、在线双版本回滚。

## 2. 先列出不符合或部分符合方案的地方

1. **多轮查询未实现**：没有 `session_id`、持久化状态、追加/替换/移除语义；案例二、案例三按方案标记为后续能力，不阻塞本期单轮验收。
2. **精确扫描量限制未实现**：当前实际限制是 MySQL `MAX_EXECUTION_TIME`、SQL `LIMIT`、应用层超时和结果截断；不能将其表述为扫描行数限制。
3. **Qdrant/ES 仅完成派生构建和辅助验证**：当前主链路由配置、规划器和白名单决定最终语义；真实阈值检索本次未命中，召回质量需要后续调查。
4. **LLM 不是固定短语的唯一解析入口**：为保证已确认指标和维度稳定，固定业务短语使用确定性归一化，未知表达仍调用 LLM；这是稳定性保护，不改变指标口径，但复杂自然语言覆盖仍有限。
5. **没有在线双版本或自动化回滚机制**：回滚依赖旧代码/配置和开发环境派生数据重建。
6. **真实安全拒绝未对数据库执行破坏性语句验证**：DML/DDL、多语句、越权对象和注入值由 SQLGlot/阶段四自动化测试验证，真实环境只执行只读查询。
7. **配置和示例环境仍需提交前处理凭据**：当前个人开发阶段保留 YAML 配置方式；真实密码/API Key 在 Git 提交前必须替换并轮换。

以上是本次自审发现的边界，不在本次报告阶段扩大修复范围。

## 3. 按方案章节逐条对照

### 3.1 方案第 3 节：业务口径与样本语义

**已实现**

- `fact_order` 保持一行一个订单，`order_id` 为订单主键：`conf/meta_config.yaml`、`docker/mysql/dw.sql`。
- `order_amount` 映射 `paid_amount`，`order_quantity` 映射 `product_quantity`。
- 四个稳定指标已配置：`paid_amount`、`product_quantity`、`order_count`、`average_quantity_per_order`：`conf/meta_config.yaml`、`app/conf/meta_config.py`。
- `order_count` 使用 `COUNT(DISTINCT fact_order.order_id)`。
- AOV 仅作为 `average_quantity_per_order` 别名；GMV 不自动映射。
- 比率按当前分组/过滤范围计算，分母为零使用 `NULLIF`：`app/planner/planner.py`、`app/compiler/sql_compiler.py`。

**验证**

- 2025 年 1 月：订单实付金额 `109030.5`，商品购买数量 `149`，订单数 `40`，平均每单购买件数 `3.7250`。

### 3.2 方案第 4 节：总体架构与链路

**已实现**

- 结构化意图：`app/intent/`、`app/agent/nodes/parse_intent.py`。
- 时间解析：`app/time/parser.py`、`app/agent/nodes/resolve_time.py`。
- 计划和语义校验：`app/planner/`、`app/agent/nodes/plan_query.py`。
- 确定性 SQL 编译：`app/compiler/sql_compiler.py`、`app/agent/nodes/generate_sql.py`。
- AST 安全校验：`app/security/sqlglot_validator.py`、`app/agent/nodes/validate_sql.py`。
- 执行和结果限制：`app/repositories/mysql/dw/dw_mysql_repository.py`、`app/agent/nodes/execute_sql.py`。
- SSE 输出：`app/services/query_service.py`、`app/api/routers/query_router.py`。

**部分实现**

- Qdrant/ES 节点和仓储仍存在，但当前确定性主链路不依赖召回结果决定最终语义；这符合“辅助召回、不决定最终语义”的安全要求，但不是完整的召回增强链路。

### 3.3 方案第 5～6 节：语义配置、元数据与索引

**已实现**

- 配置包含 `model`、`tables`、`datasets`、`relationships`、`dimensions`、`time_dimensions`、`metrics`：`conf/meta_config.yaml`。
- 配置静态校验和 DW schema 校验：`app/conf/meta_config.py`。
- 元数据实体、模型、Mapper、Repository 和表结构：`app/entities/`、`app/models/`、`app/repositories/mysql/meta/`、`docker/mysql/meta.sql`。
- Qdrant collection：`data-agent-column`、`data-agent-metric`。
- Elasticsearch index：`data-agent-value`，与已确认配置一致。
- 本次环境检查结果：`table_info=5`、`column_info=24`、`metric_info=4`、`dataset=1`、`relationship=4`、`time_dimension=1`；ES 文档数 75。

**部分实现和限制**

- 没有保存配置摘要/版本到所有派生资源并做运行时一致性比对；配置有模型 ID/版本，但当前验收主要核对结构和数据计数。
- 构建脚本会创建/写入派生资源，但没有通用的版本切换和在线迁移机制。

### 3.4 方案第 7～8 节：意图、时间、澄清、规划与 LangGraph

**已实现**

- 意图使用结构化模型和状态：`app/intent/models.py`。
- UTC+8 当前时间及测试 `reference_time` 注入：`app/time/parser.py`、`app/agent/context.py`、`app/agent/nodes/resolve_time.py`。
- 最近 N 天按自然日、包含今天、闭区间；月份缺年份进入 `needs_clarification`。
- 不支持时间表达式进入 `unsupported`；澄清/拒绝不会生成或执行 SQL：`app/agent/nodes/intent_terminal.py`、`app/agent/graph.py`。
- 规划器从语义配置读取指标、维度、关系、聚合和限制；从事实表 BFS 选择启用关系，并阻断无路、最短路径歧义和非法组合：`app/planner/planner.py`。

**部分实现**

- 固定确认短语优先走确定性归一化，未知措辞才交由 LLM；因此不能声称所有自然语言都已完成真实 LLM 集成覆盖。
- 当前不实现多轮状态。

### 3.5 方案第 9 节：SQL 编译、安全和资源限制

**已实现**

- MySQL 方言和确定性 SQL：`app/compiler/sql_compiler.py`。
- 用户过滤值使用参数绑定；表、字段、JOIN、函数和指标表达式来自白名单/语义模型。
- SQL 自动添加 `LIMIT`，支持 `MAX_EXECUTION_TIME`。
- 应用层使用 `asyncio.wait_for` 实现查询超时。
- 结果读取 `max_rows + 1` 判断截断，并返回截断元信息；已区分用户 LIMIT 与系统 `max_rows`：用户未指定 LIMIT 或指定值超过系统上限时，SQL 使用 `max_rows + 1` 进行探测，用户指定不超过系统上限时保留用户 LIMIT。
- SQLGlot 独立解析 MySQL AST，拒绝 DML、DDL、多语句、通配字段、未授权表/字段/函数/JOIN、未绑定过滤值。
- `correct_sql → execute_sql` 直通路径已从工作流移除；自动修正不会绕过完整校验。
- 数据库异常对外转换为稳定错误，避免暴露堆栈和连接信息。

**未实现**

- 精确扫描量限制未实现；`LIMIT` 只限制返回结果，不等价于扫描量限制。
- 未实现真实生产级资源配额、租户隔离和并发查询治理。

### 3.6 方案第 10 节：API/SSE 契约

**已实现**

- `POST /api/query` 仍接受：

```json
{"query":"查询 2025 年 1 月各大区的订单实付金额"}
```

- SSE 事件顺序收口为：

```text
progress → sql → result / clarification / unsupported / error → done
```

- 终态支持：`success`、`needs_clarification`、`unsupported`、`error`。
- 成功查询返回 SQL 和结果；澄清/不支持不生成或执行 SQL。
- 空结果为 `result.rows=[]`、`done.status=success`，并带 `empty` 和说明。
- 截断结果带 `truncated`、`row_count`、`max_rows`。
- 不暴露候选评分、数据库堆栈、连接串、密码、API Key；SQL 事件不发送绑定参数。
- 文件：`app/api/schemas/query_schema.py`、`app/api/routers/query_router.py`、`app/services/query_service.py`、`app/agent/nodes/intent_terminal.py`、`app/agent/nodes/execute_sql.py`。

### 3.7 方案第 11 节：测试与固定验收

**已实现**

- 配置、意图、时间、规划、SQL、SQLGlot、安全、超时、截断、错误脱敏测试。
- 固定案例文件：`tests/fixtures/stage6_cases.yaml`。
- 阶段六报告：`STAGE6_REGRESSION_REPORT.md`。
- 真实 FastAPI/SSE 和真实 MySQL 已验证；Qdrant/ES 做了只读连接、资源存在性和阈值检索检查。

**部分实现**

- 未建立完整自动化的真实环境回归脚本，当前真实 FastAPI/SSE 验证通过一次性验证脚本完成。
- 安全拒绝未在真实数据库执行，只通过单元测试构造恶意 SQL 验证。
- Qdrant/ES 当前阈值检索无命中，需后续调查。

### 3.8 方案第 12 节：实施分期

- 阶段 0：完成现状、基线和边界整理。
- 阶段 1：完成语义配置、元数据表和派生知识构建。
- 阶段 2：完成结构化意图、UTC+8 时间解析和终态。
- 阶段 3：完成确定性规划和语义校验。
- 阶段 4：完成 SQL 编译、安全、执行限制和绕过路径移除。
- 阶段 5：完成 API/SSE 契约和回归测试。
- 阶段 6：完成单轮正式回归；多轮阶段明确未开始。

## 4. 测试命令与完整结果

### 4.1 完整测试

命令：

```bash
uv run python -m unittest discover -s tests -v
```

结果：

```text
----------------------------------------------------------------------
Ran 41 tests in 0.203s

OK
```

包含：

- 阶段二意图和时间测试。
- 阶段一配置测试。
- 阶段三规划测试。
- 阶段四 SQL 编译、安全、超时、截断和错误脱敏测试。
- 阶段五 API/SSE 契约和安全测试。
- 阶段六 fixture 和空聚合结果语义测试。
- 新增 LIMIT 来源和完整编译到执行截断链路测试：未指定 LIMIT、用户 LIMIT 不超过上限、用户 LIMIT 超过上限，以及 `truncated=true` 元信息。

### 4.2 编译检查

```bash
uv run python -m compileall -q app tests
```

结果：退出码 `0`。

### 4.3 差异检查

```bash
git diff --check
```

结果：退出码 `0`。Git 仅报告工作区文件可能发生 LF/CRLF 转换，以及本机全局 ignore 文件权限警告，没有发现 diff 空白错误。

### 4.4 真实服务验收输出摘要

```text
MySQL 8 localhost:3306       reachable
Elasticsearch localhost:19200 reachable; data-agent-value docs=75
Qdrant localhost:6333        reachable; collections=data-agent-column,data-agent-metric
Embedding localhost:8081     reachable; BGE Chinese model loaded
FastAPI POST /api/query       HTTP 200; Content-Type=text/event-stream
Case 1                        5 rows; done.status=success
Missing year                  clarification; done.status=needs_clarification
Unsupported time              unsupported; done.status=unsupported
GMV                           clarification; no SQL event
Empty aggregate               rows=[]; empty=true; done.status=success
```

Docker named-pipe 状态检查在当前沙箱中因权限被拒绝，但服务级端口和 HTTP 检查成功；没有因此执行任何替代性清理操作。

### 4.5 当前工作区差异摘要

```text
git diff --stat
22 files changed, 760 insertions(+), 182 deletions(-)
```

该统计仅覆盖已被 Git 跟踪的修改文件；阶段一至阶段六的新增未跟踪文件还包括 `app/compiler/`、`app/intent/`、`app/planner/`、`app/security/`、`app/time/`、`tests/`、`STAGE6_REGRESSION_REPORT.md` 等。当前没有执行 `git commit`。

## 5. API/SSE 兼容性结论

- 请求路径仍为 `POST /api/query`。
- 请求体仍只有必需字段 `query`，原请求格式兼容。
- 响应仍为 `text/event-stream`。
- 成功事件链为 `progress → sql → result → done`。
- 澄清、不支持、错误事件链不发送 SQL 或结果猜测。
- 空结果仍是成功，不会误报为 unsupported。
- 仍存在一个实现边界：`progress` 事件数量和具体 `step` 名称可能随节点变化；消费者应按事件 `type` 和终态处理，不应依赖固定 progress 数量。

## 6. 数据库、索引构建与回滚说明

### 构建

```bash
uv sync
docker compose -f docker/docker-compose.yaml up -d
uv run python -m app.scripts.build_meta_knowledge --conf conf/meta_config.yaml
```

构建脚本 `app/scripts/build_meta_knowledge.py` 读取语义配置，通过 `MetaKnowledgeService` 将配置投影到 MySQL 元数据，并写入 Qdrant/ES 派生资源。ES 使用 `data-agent-value`；Qdrant 使用 `data-agent-column` 和 `data-agent-metric`。

### 清理边界

本次阶段六没有执行清理。测试环境若明确允许全量重置，可使用：

```bash
docker compose -f docker/docker-compose.yaml down -v
docker compose -f docker/docker-compose.yaml up -d
uv run python -m app.scripts.build_meta_knowledge --conf conf/meta_config.yaml
```

`down -v` 会删除本 Compose 管理的 `mysql_data`、`es_data`、`qdrant_data`，同时清除 `meta`、`dw`、ES 和 Qdrant 的全部派生数据；它不是只清理元数据的命令。不得在非独立测试环境执行。

### 回滚

当前没有自动回滚命令。建议流程：

1. 停止使用失败版本。
2. 恢复上一份代码和 `conf/meta_config.yaml`。
3. 在独立开发环境重新初始化或显式清理目标派生资源。
4. 重新执行 `build_meta_knowledge`。
5. 运行单轮、澄清、空结果和安全冒烟测试。

本次没有清理、删除、重建或写入任何数据库、collection、index 或 Docker volume。

## 7. 安全与资源限制实际边界

**已实际实现**

- 只读 SQL：单条 SELECT 和允许的聚合表达式。
- AST 白名单：表、字段、函数、JOIN 和 JOIN 条件均受限。
- 参数绑定：过滤值不拼接进 SQL。
- SQL 注入边界：未绑定用户值、通配字段、未授权对象、DML/DDL、多语句会被拒绝。
- 行数限制：用户 LIMIT 与系统 `max_rows` 分开处理；必要时 SQL 使用 `max_rows + 1`，应用层多取一行判断截断并返回结果元信息。
- 时间限制：MySQL `MAX_EXECUTION_TIME` 加应用层 `asyncio.wait_for`。
- 错误脱敏：对外稳定错误码和固定消息，日志只保留内部调试信息。
- 资源操作边界：本次没有执行任何清理或重建。

**不应误称为已实现**

- 精确扫描量限制。
- 全面的租户/用户权限隔离。
- 生产级并发配额、排队、熔断和审计系统。
- 在线索引双版本切换和自动回滚。

## 8. 已知问题、风险和后续建议

1. 调查 Qdrant/ES 无命中：检查向量写入、Embedding 请求、collection/index 字段映射、分数阈值和查询文本；在修复前不要把召回结果当作可靠能力。
2. 将阶段六一次性真实验收脚本固化为可重复命令，减少人工复制验证逻辑。
3. 在真实测试环境补充四项指标、商品/客户/时间组合查询的自动化结果核对，而不是只保留本次摘要。
4. 为配置模型、派生资源写入配置版本/摘要并在启动或构建时校验一致性。
5. 在提交 Git 前移除并轮换真实数据库密码、LLM API Key 和其他敏感凭据；检查日志和历史暴露。
6. 后续单独设计扫描量估算/限制、并发治理、租户隔离和在线回滚。
7. 若要扩大 LLM 覆盖，应保留固定业务短语确定性归一化，并为复杂表达增加结构化 few-shot、离线评测和失败样本回归。

## 9. 本地复现步骤

### 9.1 准备依赖

```bash
uv sync
```

准备 `conf/app_config.yaml`，确认 MySQL、Qdrant、Elasticsearch、Embedding 和 LLM 指向独立测试环境；不要把真实凭据提交到 Git。

### 9.2 初始化独立测试环境

仅限明确隔离的测试环境：

```bash
docker compose -f docker/docker-compose.yaml down -v
docker compose -f docker/docker-compose.yaml up -d
```

等待 MySQL、Elasticsearch、Qdrant、Embedding 就绪，然后构建语义派生资源：

```bash
uv run python -m app.scripts.build_meta_knowledge --conf conf/meta_config.yaml
```

### 9.3 启动 API

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 9.4 调用 SSE

```bash
curl -N http://localhost:8000/api/query `
  -H "Content-Type: application/json" `
  -d '{"query":"查询 2025 年 1 月各大区的订单实付金额"}'
```

Windows PowerShell 也可以使用：

```powershell
$body = @{ query = '查询 2025 年 1 月各大区的订单实付金额' } | ConvertTo-Json
Invoke-WebRequest http://localhost:8000/api/query -Method Post -ContentType 'application/json' -Body $body
```

### 9.5 运行测试和验收

```bash
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q app tests
git diff --check
```

阶段六固定案例位于 `tests/fixtures/stage6_cases.yaml`；真实服务验收应记录事件顺序、SQL 约束、结果、终态和环境信息，不应执行写入或清理语句。

## 10. 最终状态

- 阶段 0～5：已实现并通过对应验收。
- 阶段六单轮正式回归：已完成并通过可执行范围验证。
- 多轮查询：未实现，按方案属于后续阶段。
- 工作区：存在阶段 0～6 的未提交修改；未执行 `git commit`。
- 本报告只记录自审发现，不在本次自审中扩大功能修复范围。
