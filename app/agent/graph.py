import asyncio

from langgraph.constants import START, END
from langgraph.graph import StateGraph

from app.agent.context import DataAgentContext
from app.agent.nodes.execute_sql import execute_sql
from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.intent_terminal import intent_terminal
from app.agent.nodes.parse_intent import parse_intent
from app.agent.nodes.plan_query import plan_query
from app.agent.nodes.validate_sql import validate_sql
from app.agent.nodes.resolve_time import resolve_time
from app.agent.nodes.resolve_semantic_candidates import resolve_semantic_candidates
from app.agent.state import DataAgentState
from app.intent.models import QueryIntentStatus

graph_builder = StateGraph(state_schema=DataAgentState, context_schema=DataAgentContext)

# 添加节点
graph_builder.add_node("parse_intent", parse_intent)
graph_builder.add_node("resolve_time", resolve_time)
graph_builder.add_node("resolve_semantic_candidates", resolve_semantic_candidates)
graph_builder.add_node("plan_query", plan_query)
graph_builder.add_node("intent_terminal", intent_terminal)
graph_builder.add_node("generate_sql", generate_sql)
graph_builder.add_node("validate_sql", validate_sql)
graph_builder.add_node("correct_sql", correct_sql)
graph_builder.add_node("execute_sql", execute_sql)

# 添加关系
graph_builder.add_edge(START, "parse_intent")
graph_builder.add_edge("parse_intent", "resolve_semantic_candidates")
graph_builder.add_edge("resolve_semantic_candidates", "resolve_time")
graph_builder.add_conditional_edges(
    "resolve_time",
    lambda state: "plan_query" if state["query_intent"].status == QueryIntentStatus.READY else "intent_terminal",
    {"plan_query": "plan_query", "intent_terminal": "intent_terminal"},
)
graph_builder.add_conditional_edges(
    "plan_query",
    lambda state: "generate_sql" if state["query_intent"].status == QueryIntentStatus.READY else "intent_terminal",
    {"generate_sql": "generate_sql", "intent_terminal": "intent_terminal"},
)
graph_builder.add_edge("generate_sql", "validate_sql")

graph_builder.add_conditional_edges(
    "validate_sql",
    lambda state: (
        "execute_sql"
        if state["error"] is None
        else "correct_sql"
        if state.get("correction_eligible", False) and state.get("correction_attempts", 0) == 0
        else "intent_terminal"
    ),
    {"execute_sql": "execute_sql", "correct_sql": "correct_sql", "intent_terminal": "intent_terminal"},
)
graph_builder.add_conditional_edges(
    "correct_sql",
    lambda state: "execute_sql" if state["error"] is None else "intent_terminal",
    {"execute_sql": "execute_sql", "intent_terminal": "intent_terminal"},
)
graph_builder.add_edge("execute_sql", END)
graph_builder.add_edge("intent_terminal", END)

graph = graph_builder.compile()



if __name__ == '__main__':
    async def test():
        # embedding_client_manager.init()
        # qdrant_client_manager.init()
        # es_client_manager.init()
        # meta_mysql_client_manager.init()
        # dw_mysql_client_manager.init()
        #
        # async with meta_mysql_client_manager.session_factory() as meta_session, dw_mysql_client_manager.session_factory() as dw_session:
        #     meta_mysql_repository = MetaMySQLRepository(meta_session)
        #     dw_mysql_repository = DWMySQLRepository(dw_session)
        #     column_qdrant_repository = ColumnQdrantRepository(qdrant_client_manager.client)
        #     value_es_repository = ValueESRepository(es_client_manager.client)
        #     metric_qdrant_repository = MetricQdrantRepository(qdrant_client_manager.client)
        #
        #     context = DataAgentContext(
        #         embedding_client=embedding_client_manager.client,
        #         column_qdrant_repository=column_qdrant_repository,
        #         value_es_repository=value_es_repository,
        #         metric_qdrant_repository=metric_qdrant_repository,
        #         meta_mysql_repository=meta_mysql_repository,
        #         dw_mysql_repository=dw_mysql_repository
        #     )
        #     state = DataAgentState(query="统计去年各地区的销售总额")
        #     async for chunk in graph.astream(input=state, context=context, stream_mode="custom"):
        #         print(chunk)
        #
        # await qdrant_client_manager.close()
        # await es_client_manager.close()
        # await meta_mysql_client_manager.close()
        # await dw_mysql_client_manager.close()
        print(graph.get_graph().draw_mermaid())

    asyncio.run(test())
