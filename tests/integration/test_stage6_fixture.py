
import unittest
from pathlib import Path

import yaml


class Stage6FixtureTests(unittest.TestCase):
    def test_stage6_fixture_contains_required_cases(self):
        fixture = yaml.safe_load(Path(__file__).parents[1].joinpath('fixtures', 'stage6_cases.yaml').read_text(encoding='utf-8'))
        ids = {case['id'] for case in fixture['cases']}
        self.assertTrue({'case_1_region_metrics_january_2025', 'reject_gmv', 'empty_success'} <= ids)
        self.assertEqual(fixture['scope'], 'single_turn')


if __name__ == '__main__':
    unittest.main()
