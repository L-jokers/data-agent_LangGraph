import unittest

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState


LEGACY_NODES = {
    "extract_keywords",
    "recall_column",
    "recall_metric",
    "recall_value",
    "merge_retrieved_info",
    "filter_table",
    "filter_metric",
    "add_extra_context",
}


class T9BLegacyMigrationTests(unittest.TestCase):
    def test_formal_graph_contains_only_new_candidate_resolution_path(self):
        graph_nodes = set(graph.get_graph().nodes)
        self.assertTrue({
            "parse_intent",
            "resolve_semantic_candidates",
            "resolve_time",
            "plan_query",
            "generate_sql",
            "validate_sql",
            "execute_sql",
        } <= graph_nodes)
        self.assertTrue(LEGACY_NODES.isdisjoint(graph_nodes))

        edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
        self.assertFalse(any(source in LEGACY_NODES or target in LEGACY_NODES for source, target in edges))
        self.assertIn(("parse_intent", "resolve_semantic_candidates"), edges)
        self.assertIn(("resolve_semantic_candidates", "resolve_time"), edges)

    def test_legacy_candidate_state_fields_are_not_part_of_formal_contract(self):
        state_keys = set(DataAgentState.__annotations__)
        context_keys = set(DataAgentContext.__annotations__)
        for key in (
            "keywords",
            "retrieved_columns",
            "retrieved_metrics",
            "retrieved_values",
            "table_infos",
            "metric_infos",
            "embedding_client",
            "column_qdrant_repository",
            "value_es_repository",
            "metric_qdrant_repository",
        ):
            self.assertNotIn(key, state_keys | context_keys)
        self.assertIn("semantic_candidates", state_keys)
        self.assertIn("semantic_candidate_retriever", context_keys)


if __name__ == "__main__":
    unittest.main()
