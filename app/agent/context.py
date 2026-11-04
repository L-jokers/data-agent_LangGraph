from datetime import datetime
from typing import Any, NotRequired, TypedDict

from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.services.semantic_model_snapshot import SemanticModelSnapshot
from app.services.semantic_candidate_retriever import SemanticCandidateRetriever
from app.security.query_limits import QueryLimits


class DataAgentContext(TypedDict):
    meta_mysql_repository: MetaMySQLRepository
    dw_mysql_repository: DWMySQLRepository
    # 阶段二新增：测试时注入固定参考时间；正式运行未注入时使用UTC+8当前时间。
    reference_time: NotRequired[datetime]
    query_limits: NotRequired[QueryLimits]
    semantic_model_snapshot: SemanticModelSnapshot
    semantic_candidate_retriever: SemanticCandidateRetriever
    trusted_query_chain: NotRequired[Any]
