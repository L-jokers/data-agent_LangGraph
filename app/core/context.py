from contextvars import ContextVar

# 全量上下文ContextVar
request_id_ctx_var = ContextVar("request_id", default="1")

