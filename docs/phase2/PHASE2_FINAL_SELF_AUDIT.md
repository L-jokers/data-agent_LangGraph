# 第二阶段最终自审报告

> 用途：提交评审方案 Agent 进行最终审核。本文只汇总当前工作区代码、测试、既有状态/交接记录和用户明确确认；不替代用户验收记录，也不把未在仓库留痕的真实服务执行细节伪装成可复现证据。
>
> 自审日期：2026-11-04。未访问真实外部服务；未执行 DDL/DML、索引构建/写入、激活、迁移、清理或提交。

## 1. 总结与阶段状态

- T0 至 T9 的已授权实施阶段：用户声明均已完成验收；T9-A、T9-B、T9-C 的验收状态按用户本轮明确说明记录为“通过”。
- T9-C：**已验收通过（用户确认）**。用户确认正式全链路回归已实现，T9-C 验收清单均已完成。此前 `PHASE2_DEVELOPMENT_STATUS.md` 仍把 T9-C 标为“部分完成”，并记载早期真实请求在意图解析阶段失败；该记录未包含用户后来完成的正式回归结果，现已过时。本文不修改该状态文件，仅明确该差异，供评审 Agent 对照。
- 本轮本地复核：全量 unittest 151 项通过；compileall 通过；`git diff --check` 通过（有 LF/CRLF 提示）。本轮没有重新执行真实服务测试。
- **证据分级**：代码与 mock 测试可从当前仓库复核；T9-C 后续真实正式链路通过属于用户明确验收声明，细粒度运行日志/场景结果/计数未留存在当前状态文档，不能据此声称本轮重新复验。
- 本次没有开始任何后续阶段，没有代码功能改动；唯一新增文件为本报告。

## 2. 按方案逐阶段对照

方案来源：`docs/phase2/SECOND_PHASE_TECHNICAL_DEVELOPMENT_PLAN.md`。阶段验收以用户验收为准；“偏差/留痕”列说明仓库内能否复现，并非推翻用户验收。

| 阶段 | 状态/验收 | 主要完成项及实现位置 | 验收清单与偏差 |
|---|---|---|---|
| T0 基线盘点 | 完成；作为基线阶段已通过 | `AGENTS.md`、Git 工作区、配置结构、数据库脚本、检索组件、主图/API 与测试盘点 | 未操作外部资源。当前仍有大量未提交工作区改动；本轮完整保护。 |
| T1 MySQL 版本化语义元数据（含 handoff 续作） | 完成，用户已验收 | `app/models/*mysql.py`、`app/repositories/mysql/meta/meta_mysql_repository.py`、`app/services/meta_knowledge_service.py`、`app/scripts/build_meta_knowledge.py`、`docker/mysql/meta.sql` | 版本隔离、active 指针、draft 幂等/冲突、事务激活门禁、复合外键 flush 顺序修复。阶段测试见第 8 节。无真实 DDL/迁移由本轮执行。 |
| T2 SemanticModelSnapshot | 完成，用户已验收 | `app/services/semantic_model_snapshot.py`；`app/agent/context.py`；QueryService/Graph 绑定 | 指定版本整体加载与关联校验；构建端可读显式 draft；查询首次选 active、恢复固定会话版本；生产链路不 YAML fallback。测试包括 snapshot 不可变、跨版本拒绝、draft 边界。 |
| T3-A 派生索引构建及激活门禁 | 完成，用户已验收 | `app/services/semantic_index_builder.py`、`semantic_index_verification.py`、`app/clients/semantic_index_clients.py`、`app/scripts/build_semantic_indexes.py`、`activate_semantic_version.py` | 构建、幂等 ID、部分失败识别、完整性/可检索性验证、版本/配置/资源绑定验证记录和失败关闭激活。具体范围见第 4 节。 |
| T3-B Retriever 组件 | 完成，用户已验收 | `app/services/semantic_candidate_retriever.py`、`app/clients/semantic_index_clients.py` | exact/lexical/vector/hybrid、阈值/分差、维度约束、MySQL 回查、只读降级。组件在 T9-A 才正式接入主图。 |
| T4 意图及时间结构化 | 完成，用户已验收 | `app/intent/llm_output.py`、`models.py`、`time_coverage.py`、`app/time/parser.py`、`app/agent/nodes/resolve_time.py`、`prompts/parse_intent.prompt` | 时间完整性、UTC+8、周日开周、离散日期/多个闭区间、澄清与不支持状态、离散条件编译。保留失败关闭；不能把自然语言时间默认为无时间。 |
| T5 指标依赖与规划 | 完成，用户已验收 | `app/services/metric_dependency_validator.py`、`app/planner/planner.py`、`app/agent/nodes/plan_query.py` | 依赖深度（目标至基础指标的边数）、环/未知引用/跨版本/粒度/重复聚合/关系路径与缺项澄清；澄清恢复完整重解析、重规划。 |
| T6 JSON AST 与确定性编译 | 完成，用户已验收 | `app/compiler/expression_ast.py`、`app/compiler/sql_compiler.py`、`app/planner/models.py` | AST 节点/函数/算子白名单、依赖展开、CASE/条件聚合、受限窗口；业务值参数绑定；普通指标元数据变化不需按 ID 写分支。 |
| T7 SQLGlot 安全验证与有限修正 | 完成，用户已验收 | `app/security/sqlglot_validator.py`、`app/services/sql_correction.py`、`app/services/trusted_query_chain.py`、`app/agent/nodes/{validate_sql,correct_sql}.py` | 只读/对象/字段/JOIN/函数/窗口/LIMIT/参数白名单；确定性最多一次修正；生产图接入可信链重跑，只有安全校验成功才执行/暴露 SQL。 |
| T8 MySQL 会话/API/SSE/并发 | 完成，用户已验收 | `app/models/application_session_mysql.py`、`app/repositories/mysql/application_session_repository.py`、`app/services/clarification_recovery.py`、`app/services/query_service.py`、`app/api/routers/query_router.py` | 5 分钟逻辑 TTL、版本绑定、clarification_id、乐观锁状态推进、幂等终态、不保存完整结果、execution_unknown 不自动重跑。mock 并发测试见第 8 节；本轮未进行真实会话写入/并发。 |
| T9-A Retriever 正式接线 | 完成，用户已验收 | `app/agent/nodes/resolve_semantic_candidates.py`、`app/agent/graph.py`、`app/agent/context.py`、`app/services/query_service.py` | 正式 Graph context 注入 Retriever；结果驱动 exact/auto/clarification/unresolved；查询绑定 snapshot 版本。 |
| T9-B 旧召回迁移 | 完成，用户已验收 | `app/agent/graph.py`、`state.py`、`context.py`、`legacy_state.py`；旧 `app/agent/nodes/*` 文件保留 | 正式主图仅有新候选链；旧节点经依赖盘点后保留为审查/兼容代码，不注册、不连边、不作为候选授权事实；资源未随代码迁移删除。 |
| T9-C 全链路回归与交付 | **完成，用户已验收** | 正式入口 `QueryService → LangGraph`；具体组件见第 3–7 节 | 用户确认本方案验收清单均已完成。仓库状态文档未同步后续真实成功回归，保留早期失败叙述；详细真实运行记录/次数/结果行数没有在该文档留痕，故自审不虚构具体数值。 |

### 验收项状态口径

- **通过**：阶段由用户确认验收；T9-C 的全部验收清单按用户最新确认通过。
- **失败**：本轮本地全量测试、编译或 diff 检查无失败。历史真实 LLM 请求曾因 schema/time 输出不合规失败关闭；该历史失败不能当作成功路径证据，也不能覆盖用户后续验收结论。
- **未测试/本轮未复验**：本轮没有连接真实 MySQL、ES、Qdrant、Embedding、LLM 或 API 部署；真实 T9-C 的后续正式回归由用户完成验收，但没有新增逐请求运行日志。T8 真实会话写入/并发的本轮复验未执行。

## 3. 主要实现结构与数据模型

| 模块 | 职责与数据流 | 当前限制/审计说明 |
|---|---|---|
| `app/services/query_service.py` `QueryService.query()` | API 正式入口；加载 snapshot、绑定 semantic version、组装 `DataAgentContext`、Graph streaming、会话状态及 SSE 事件。 | 真实执行可能访问数仓并持久化 MySQL session；本次未调用。 |
| `app/agent/graph.py`、`app/agent/state.py`、`context.py` | 主图节点/路由、结构化 intent 与候选状态；context 注入 snapshot、Retriever、limits、trusted replay chain。 | 正式主图不使用旧 `retrieved_*` 候选状态作为语义事实。旧节点文件仍存在但不注册。 |
| `app/agent/nodes/parse_intent.py`、`app/agent/llm.py` | 调 LLM 提取业务表达/时间结构；适配供应商响应；错误走安全终态。 | LLM 不负责生成语义 ID、口径、SQL或最终时间值。Provider 约束不能只按客户端参数推定为已生效。 |
| `app/intent/llm_output.py`、`models.py`、`time_coverage.py` | 响应提取、严格字段/类型/schema 校验、时间来源覆盖检查和结构化错误。 | 已有 mock 覆盖；实时 provider 行为需要真实环境日志才能复核。 |
| `app/services/semantic_model_snapshot.py` `SemanticModelSnapshotLoader` | 查询按 active 或指定 session version 加载完整版本；构建命令允许显式 draft；校验跨实体关联一致性。 | snapshot 是本次请求的语义事实快照；不得在查询中重新选版本。 |
| `app/services/semantic_candidate_retriever.py` | exact + ES lexical + 必要 Qdrant vector、合并排序/阈值、版本/类型/维度过滤、snapshot 最终回查。 | 精确映射需要唯一 exact；auto 需要开关、分数和分差；缺少 Top2/不够阈值转澄清；无候选 unresolved；索引不可用降级，不创建/重建/补写。 |
| `app/clients/semantic_index_clients.py` | ES/Qdrant 只读 lexical/vector 客户端适配。 | query embedding 是每条用户查询的单条 embedding；没有索引写接口进入查询路径的意图。 |
| `app/services/metric_dependency_validator.py`、`app/planner/planner.py` | 用绑定 snapshot 校验指标依赖、口径、关系路径、粒度、时间/过滤条件，生成 QueryPlan。 | 缺项确定性澄清；不得由 LLM 猜指标口径。 |
| `app/compiler/expression_ast.py`、`sql_compiler.py` | 白名单 AST 到 SQL 的确定性编译；抽取对象/列/函数依赖；参数绑定和限额。 | SQL 函数/表达式能力需代码审核；AST 不能容纳任意 SQL 文本。 |
| `app/security/sqlglot_validator.py`、`trusted_query_chain.py`、`sql_correction.py` | SQLGlot 校验；仅批准结构可有限修正一次，重新执行 intent validation→plan→plan validation→compile→SQLGlot。 | 失败或链组件/snapshot 缺失失败关闭；不允许自由 SQL 修复或跳过安全校验。 |
| `app/models/application_session_mysql.py`、`application_session_repository.py`、`clarification_recovery.py` | session/turn/clarification、TTL、semantic version、state_version 乐观锁及恢复请求。 | 不持久化完整查询结果；执行状态不明时不自动重跑。 |
| `app/api/routers/query_router.py`、`app/api/schemas/query_schema.py` | 正式 API 输入、SSE 事件/终态。 | 本轮未启动真实部署进行 API/SSE 外部复验。 |

## 4. 元数据、快照、索引及激活

### SemanticModelSnapshot 与版本边界

- MySQL 为语义事实源；`SemanticModelSnapshotLoader.load_for_query()` 只加载 active/绑定版本，`load_for_build(version_id)` 仅供明确指定版本的构建工作流读取 draft。
- 首次请求选择 active 并将 `version_id` 绑定进 context/session；意图解析、候选回查、planner、compiler、SQL correction replay 使用同一 snapshot/version。澄清恢复继续 session 绑定版本，不重新取 active。
- 版本模型：`semantic_model_version`、`semantic_model_current`；语义表实体使用 `version_id` 复合键/关联。索引验证记录为 `semantic_index_verification`；应用会话为 `application_session`（实际表名以模型/DDL为准）。

### 初始化/迁移行为

- `docker/mysql/meta.sql` 是 MySQL 元数据库初始化 DDL，包含版本、current 指针及版本化语义表/外键；不是自动升级/迁移框架。本轮没有执行它。
- `app/scripts/build_meta_knowledge.py` 通过显式 `--version-id` 从 YAML 初始化 MySQL draft；相同版本相同内容幂等，不同内容拒绝覆盖；不会自动激活或构建 ES/Qdrant。
- 索引构建独立读取 MySQL 指定版本；显式激活脚本调用 repository 门禁。没有授权时，上述脚本是写操作，不能由 Agent 擅自运行。

### 索引命令、来源、payload 与覆盖

- 构建接口：`uv run python -m app.scripts.build_semantic_indexes --version-id <draft-version> --target both --es-index <index> --qdrant-collection <collection>`；可按 `--target es` / `qdrant` 单资源构建，但不满足完整激活门禁。
- 激活接口：`uv run python -m app.scripts.activate_semantic_version --version-id <version> --es-index <index> --qdrant-collection <collection> --embedding-model <model> --embedding-dimension <dimension>`。
- 来源为 MySQL 指定版本 snapshot，不从 YAML 构建索引。覆盖 metric 名称/别名/描述、dimension 名称/别名、field 名称/别名/描述，以及仅限声明维度对应列的声明 examples 过滤值；不全库扫描业务值。
- payload 包含 `semantic_type`、稳定 ID、`version_id`、展开文本 `text`、展示名；过滤值还带 `dimension_id`、`table_id`、`column_id`。
- document/point 确定性 ID 基于版本、实体/展开文本和构建配置；相同输入可幂等重试，配置改变生成不同 manifest/ID，不能沿用旧验证状态。
- embedding 失败、ES bulk 单项失败、Qdrant 部分写入、覆盖/ID/payload/可检索性不足均不能记录为成功；门禁要求成功验证记录与版本内容、构建配置及目标 index/collection/manifest 匹配且未过期。门禁拒绝不匹配或失败状态；只显式激活。
- T3-A 用户验收通过；T9-C 初始化、构建、验证、显式激活的先后顺序及资源操作由用户完成/确认。当前自审未重复执行任何写操作。

## 5. 检索与主图：只读及候选边界

- 主图注册新 candidate resolution 路径；T9-B 测试 `test_formal_graph_contains_only_new_candidate_resolution_path` 和 state 契约测试证明旧候选字段已从正式 contract 移除。旧节点文件保留，但不构成第二条可运行链。
- `SemanticCandidateRetriever.lexical_search()` 使用 ES；`vector_search()` 对当前用户 query 执行单条 embedding 后使用 Qdrant；`hybrid_search()` 依精确匹配、必要 lexical/vector、统一候选分类和 MySQL snapshot 回查。
- 查询调用只发送 index/collection 检索，不执行 create index/collection、全量 metadata scan、全量 embedding、upsert 或隐式初始化。`test_exact_match_uses_snapshot_and_no_index_write`、`test_unavailable_index_degrades_without_initialization`（`tests/test_semantic_candidate_retriever.py`）覆盖无索引写入及不可用降级；需以本地测试结果为证，不等同真实集成。
- 版本/类型过滤被传给 ES/Qdrant；filter value 额外以 `dimension_id` 约束。候选稳定 ID 必须能在同一版本 snapshot 回查。精确映射仅唯一名称/别名；非精确 auto 需要模糊开关、score 与 Top1/Top2 margin；无 Top2/分差不足转 clarification；无候选 unresolved/unsupported。冷启动关闭模糊 auto；索引缺失/不可用只走有限降级，不触发写入/扫描。
- T9-C 用户确认真实 ES lexical、Qdrant vector、版本/类型/维度限制及 MySQL snapshot 回查等全链路验收通过；先前状态文件留有早期只读探测数据，但没有记录后续通过的逐场景调用/命中数。本轮未连接这些服务，不报告本轮命中数量。

## 6. 表达式 AST、SQL 安全与修正重跑

- AST 定义及实现：`app/compiler/expression_ast.py`；SQL 生成：`app/compiler/sql_compiler.py`。批准节点涵盖已实现的字段/指标依赖引用、固定算子/函数、CASE、条件聚合与受限窗口；未知节点、函数、算子、字段、未批准 frame、依赖环/跨版本/超深度/重复聚合等失败关闭。窗口仅最终输出，不能放进 WHERE/GROUP BY/JOIN ON 或作为其他 metric 输入；不支持的 SQL 特性不自动扩展。
- 业务值进入 params；表/列/JOIN/函数白名单从已校验的 QueryPlan/snapshot 构造。compiler 将服务端 `QueryLimits` 作为显式参数，plan 不能传入资源限额覆盖这些参数。
- `app/security/sqlglot_validator.py` 解析最终 SQL 并校验只读语句、表列、JOIN/函数、窗口位置、LIMIT 与参数集。SQL 安全失败不做“修到通过”的 LLM 改写。
- T7 修正决策为确定性且最多一次；可信 replay 基于同一 snapshot/version 重新运行 intent validation、plan、plan validation、compile 和 SQLGlot。Graph 只有安全校验成功才转 execute；修正后 SQL 同样不得提前 SSE 暴露。
- 测试证据：`tests/test_t6_expression_ast.py`、`tests/test_t7_sql_security_correction.py`、`tests/test_t7_trusted_graph.py`，详见第 8 节。

## 7. 会话、SSE 与请求限额

- `QueryService` 设置 `QueryLimits(max_rows=20, timeout_seconds=60.0, max_execution_time_ms=60000)` 和请求 `asyncio.timeout(180s)`；compiler 使用这些服务端参数生成 `CompiledQuery`，执行节点只使用编译结果中的限制。
- 会话恢复读取 session 绑定的 semantic version，并要求有效 `clarification_id`；TTL 为 5 分钟逻辑过期。MySQL repository 使用 status/state_version/clarification_id/expires_at 条件进行条件更新，抢占失败的并发请求读取当前状态作为幂等结果。
- 不支持成功查询后的任意追加/替换/删除条件。请求超时或异常导致状态不确定时发 `execution_unknown`，不自动重试 SQL；不保存完整结果集。
- T8 mock 测试覆盖首次 session/SSE、绑定版本恢复、过期、clarification mismatch、并发只 claim 一次及 unknown terminal。当前自审未对真实 MySQL session 表执行读写或并发测试；用户已验收阶段不等于本轮真实复验。
- 风险提示：`QueryService` 在正式 dependencies 中注入 `ApplicationSessionRepository`，成功请求涉及 MySQL session 状态写操作。真实重新测试前应检查有效授权。本轮没有任何会话写入。

## 8. 测试与集成证据

### 本轮实际执行（2026-11-04）

| 命令 | 结果 | 真实外部服务/写入 | 覆盖与不能证明的内容 |
|---|---|---|---|
| `uv run python -m unittest discover -s tests -v` | **151 tests，OK** | 不连接真实外部服务；执行 fake/mock 测试 | 覆盖当前仓库所有 unittest；不能证明真实 ES/Qdrant/MySQL/LLM 查询成功。 |
| `uv run python -m compileall -q app tests` | **通过** | 无 | Python 编译检查；不验证运行时服务。 |
| `git diff --check` | **通过**；Git 提示部分文件 LF 将转 CRLF | 无 | 无 diff 空白错误；换行提示不是测试失败。 |

### Mock/单元测试覆盖（本轮全量套件通过）

- 版本/snapshot：`tests/test_semantic_model_snapshot.py`、`tests/test_semantic_versioning.py`、`tests/test_meta_knowledge_service.py`。
- 索引构建：`tests/test_semantic_index_builder.py`（构建配置、幂等、embedding/ES/Qdrant 失败、激活门禁）；全部为 fake/mock，不是实际构建记录。
- Retriever/主图/旧链路：`tests/test_semantic_candidate_retriever.py`、`tests/test_t9_a_retriever_graph.py`、`tests/test_t9_b_legacy_migration.py`。
- 意图/时间：`tests/test_intent_and_time.py`、`tests/test_t4_time_chain.py`、`tests/test_t9c_intent_output_boundary.py`。
- 指标规划/AST/安全修正：`tests/test_t5_metric_planning.py`、`tests/test_t6_expression_ast.py`、`tests/test_t7_sql_security_correction.py`、`tests/test_t7_trusted_graph.py`。
- 会话/SSE/结果语义：`tests/test_t8_sessions.py`、`tests/api/test_query_api_contract.py`、`tests/security/test_sse_security.py`、`tests/integration/test_stage6_result_semantics.py`。路径名含 `integration` 的结果语义用例使用隔离 repository/mock，不能视为真实数据库集成。
- 日志中可见测试输出含 Loguru `%s` 字面占位符（例如结果行数/异常文本的日志调用）。本轮不改业务代码；这可能说明相关日志格式化未按 Loguru `{}` 风格生效，应由后续代码评审确认，但当前日志仍避免在本文记录 SQL/结果内容。不是本轮 unittest 失败。

### 真实服务与端到端验收

- MySQL/ES/Qdrant/LLM 的 T9-C 后续正式回归：用户明确声明已实际完成并验收通过；按用户声明记录为**通过**。本轮自审没有重跑真实服务，也没有输出任何业务行、SQL、原始 LLM 响应或凭据。
- 已存在的 `PHASE2_DEVELOPMENT_STATUS.md` 只记录早期真实只读检索命中及一次 QueryService/Graph 请求在 `needs_clarification` 终止（该请求不是成功链路）；其中记录 13/30 调用预算及 T9-C 部分完成。该记录明显早于用户所述后续完整成功回归，应视为历史快照，不是当前验收结论。
- 真实 T9-C 成功回归的逐项问题、调用次数、重复次数、真实结果行数、LLM/provider 输出 schema 细节、实际安全拒绝/修正样例没有追加在状态文件。本报告不能给这些细节填造值；如评审要求可审计重现，需要用户提供/授权以脱敏形式补充证据。

### 本轮未执行

- 未连接真实 MySQL/ES/Qdrant/embedding/LLM；未执行真实 QueryService/API/SSE 成功请求。
- 未运行索引构建、MySQL draft 初始化、激活脚本、DDL/DML、数据库迁移、索引/collection 创建或写入。
- 未对真实 MySQL session 执行恢复/过期/并发测试。
- 用户补充：上述未执行内容和测试都由用户人工进行测试和实现了，完成验收。

## 9. 资源影响、风险与人工授权

- 本轮资源影响：仅读取本地源码/文档/Git 状态并运行本地 unittest、compileall、diff 检查；未触碰外部服务或真实数据，没有写入、初始化、激活、删除或 Docker 操作。
- 真实索引/元数据库脚本属于有副作用的构建/激活入口；即使此前用户已确认资源初始化完成，也不能据此由 Agent 擅自重复执行。将来任何写 SQL、DDL、初始化/迁移、索引构建/upsert、激活、删除或 Docker volume 操作，仍须先明确目标、影响、失败处置并获单独授权。
- `conf/app_config.yaml` 含敏感配置；本报告不复述其值。检查配置时只应记录键/能力，不得复制密码、token、完整连接串或模型原始输出。
- 主要剩余审计风险是“用户已完成真实验收，但后续结果未写入状态文档”：可确认验收结论，却无法从仓库独立复演其每一条真实服务调用/问题/次数。T8真实并发和会话数据库行为亦未由本次自审复测。

## 10. 工作区状态与变更保护

- 初始 `git status --short` 显示大量已修改文件和未跟踪文件，覆盖 `AGENTS.md`、`app/`、`conf/meta_config.yaml`、`docker/mysql/meta.sql`、提示词、测试、`PHASE2_DEVELOPMENT_STATUS.md`、`docs/phase2/` 和阶段说明文档等。具体清单应以当前 Git 状态为准；本报告不复制完整 diff。
- 现有改动跨 T1-T9 多阶段，且不少文件是跨阶段共享文件；不要回滚、clean、reset、checkout 或覆盖任何现有内容。`conf/app_config.yaml` 为敏感配置，不纳入报告内容。
- 自审期间唯一写入：新增 `PHASE2_FINAL_SELF_AUDIT.md`。没有编辑业务代码、状态文档或配置；没有提交或创建分支。

## 11. 评审结论

- 阶段验收状态：T0–T9 均按用户确认记录为已完成/已验收；T9-C 用户确认完整正式链路回归通过。
- 本地复验结论：151 项 unittest、compileall、diff check 均通过。
- 真实服务结论：T9-C 真实回归**已由用户确认通过**，但本轮未重新执行；既有 `PHASE2_DEVELOPMENT_STATUS.md` 未记录用户后来完成的逐项结果，且仍保留过期的 T9-C 部分完成结论。
- 因而本报告可以报告“按用户验收全部通过”，但不能声称“本轮独立重跑了真实链路”，也不能为缺失的真实调用数/问题明细补造证据。建议评审方案 Agent 将用户的正式验收确认与过期状态记录核对，并按项目归档约定决定是否由用户另行授权更新阶段状态文档；本次严格不修改该状态文件。
- 不开始任何后续阶段；报告交付后等待评审。

