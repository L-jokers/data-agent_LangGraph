# 智能问数系统（Data Agent）

基于自然语言的数据查询服务。系统结合业务元数据检索与大语言模型，将用户问题转换为 SQL，在数据仓库中执行，并通过 Server-Sent Events（SSE）持续返回工作流结果。

## 功能概览

- 从用户问题中提取关键词，并行召回字段、指标和字段值相关知识。
- 基于 Qdrant 向量检索表字段和指标，以 Elasticsearch 检索字段值。
- 整合元数据和补充上下文，由 LLM 生成 SQL；校验失败时尝试修正，再查询数仓。
- 通过 `POST /api/query` 以 SSE 格式流式返回处理过程及结果。
- 提供元知识构建脚本，将 YAML 中的表、字段和指标定义写入元数据存储与检索索引。

## 技术栈

Python 3.12+、FastAPI、LangChain/LangGraph、MySQL（元数据与数仓）、Qdrant、Elasticsearch、Hugging Face Text Embeddings Inference，以及兼容 LangChain 的聊天模型接口。

## 项目结构

```text
.
├── app/
│   ├── agent/             # LangGraph 状态、工作流与节点
│   ├── api/               # HTTP 路由、依赖和请求模型
│   ├── clients/           # MySQL、Qdrant、Elasticsearch、Embedding 客户端
│   ├── conf/              # 配置模型与加载器
│   ├── entities/          # 领域实体
│   ├── repositories/      # 数据访问层
│   ├── scripts/           # 元知识构建脚本
│   └── services/          # 问数与元知识服务
├── conf/
│   ├── app_config.yaml    # 服务、存储和 LLM 配置
│   └── meta_config.yaml   # 业务表、字段和指标定义
├── docker/
│   ├── docker-compose.yaml # MySQL、Elasticsearch、Kibana、Qdrant、Embedding
│   └── embedding/         # 本地 BGE 中文向量模型文件
├── prompts/               # 关键词扩展、SQL 生成/修正及筛选提示词
├── main.py                # FastAPI 应用入口
└── pyproject.toml         # Python 项目及依赖定义
```

## 环境准备

- Python 3.12 或更高版本
- [uv](https://docs.astral.sh/uv/) 包管理器
- Docker Compose
- 可访问的聊天模型 API 凭据及模型服务

安装 Python 依赖：

```bash
uv sync
```

## 启动依赖服务

在项目根目录运行：

```bash
docker compose -f docker/docker-compose.yaml up -d
```

Compose 文件启动 MySQL、Elasticsearch、Kibana、Qdrant 和本地 Embedding 服务。Embedding 容器从 `docker/embedding/bge-large-zh-v1.5` 加载模型；该目录需要包含可用的模型文件。默认端口分别为 MySQL `3306`、Elasticsearch `9200`、Kibana `5601`、Qdrant HTTP `6333`/gRPC `6334`、Embedding `8081`。

请确认 MySQL 中已创建配置所指向的 `meta` 和 `dw` 数据库，并准备好对应的数据表。当前 Compose 配置挂载 `docker/mysql` 作为初始化目录；如需通过 SQL 自动建库/建表，请将初始化脚本放入该目录。Kibana 为可选的 Elasticsearch 管理界面。

## 配置

修改 `conf/app_config.yaml`：

- `db_meta`：元数据 MySQL 连接信息。
- `db_dw`：数仓 MySQL 连接信息。
- `qdrant`：Qdrant 地址及向量维度；应与 Embedding 模型输出维度一致（当前配置为 `1024`）。
- `embedding`：Embedding 服务地址、端口和模型名。
- `es`：Elasticsearch 连接信息。
- `llm`：聊天模型名称、API Key 和 Base URL。将示例占位值替换为实际值。
- `logging`：控制台及文件日志级别、目录、轮转和保留时间。

修改 `conf/meta_config.yaml` 描述业务元数据。表定义包含表名、角色、描述和字段；字段可配置角色、描述、别名及 `sync`。指标定义包含名称、描述、相关字段和别名。请确保表名、字段名与数仓实际结构匹配，并确认指标定义符合业务口径。

配置文件中含有凭据字段。不要将真实密钥提交到版本库；生产环境应限制配置文件访问权限，并按部署环境安全注入凭据。

## 构建元知识

配置数据库和检索服务后，在项目根目录执行：

```bash
uv run python -m app.scripts.build_meta_knowledge --conf conf/meta_config.yaml
```

脚本根据元数据配置更新 MySQL 元数据，并将用于召回的字段/指标向量写入 Qdrant、字段值索引写入 Elasticsearch。修改业务元数据后，重新运行此命令以同步知识库。

## 启动 API

开发模式：

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

也可直接运行 `uv run python main.py`（监听 `0.0.0.0:8000`，不启用自动重载）。

## 调用问数接口

接口：`POST /api/query`，请求体为 JSON，字段 `query` 是自然语言问题。

```bash
curl -N http://localhost:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"统计去年各地区的销售总额"}'
```

响应为 `text/event-stream`，每个事件使用 `data: <JSON>` 格式并以空行分隔。客户端可使用浏览器的 `fetch` 流式读取或其他支持 SSE 的 HTTP 客户端消费。执行异常会以包含 `type: error` 和 `message` 的数据事件返回。

## 问数工作流

工作流在 `app/agent/graph.py` 中定义，大致按以下顺序执行：

1. 提取和扩展问题关键词。
2. 并行召回字段、字段值与指标信息，再合并检索结果。
3. 筛选相关表和指标，并补充 SQL 上下文。
4. 生成 SQL 并校验；校验发现错误时进入 SQL 修正节点。
5. 执行 SQL 并通过 SSE 输出工作流事件。

提示词位于 `prompts/`，通过 `app/prompt/prompt_loader.py` 按名称加载。可根据业务术语和 SQL 方言调整提示词，并结合实际数据验证生成结果。

## 测试与开发说明

仓库根目录的 `test.py` 当前是上下文管理器的简单示例，不是项目自动化测试套件。执行 `uv run python test.py` 可运行该示例；完整问数流程还需要 MySQL、Qdrant、Elasticsearch、Embedding 和 LLM 服务正确配置并可访问。

API 请求中间件会为每个请求生成唯一 request ID，供并发请求日志关联使用。日志配置默认写入 `logs` 目录并输出到控制台。
