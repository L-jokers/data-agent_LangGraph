import asyncio
from types import SimpleNamespace
from unittest import TestCase

from app.agent.nodes.execute_sql import _is_empty_aggregate


class Stage6ResultSemanticsTests(TestCase):
    def test_zero_aggregate_row_is_empty(self):
        self.assertTrue(_is_empty_aggregate(
            'SELECT COUNT(DISTINCT fact_order.order_id) AS order_count',
            [{'order_count': 0}],
        ))

    def test_nonzero_aggregate_row_is_not_empty(self):
        self.assertFalse(_is_empty_aggregate(
            'SELECT COUNT(DISTINCT fact_order.order_id) AS order_count',
            [{'order_count': 40}],
        ))


if __name__ == '__main__':
    asyncio.run(asyncio.sleep(0))
