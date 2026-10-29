import copy
import unittest
from pathlib import Path

import yaml

from app.conf.meta_config import MetaConfig, MetaConfigValidationError, load_meta_config


CONFIG_PATH = Path(__file__).parents[1] / "conf" / "meta_config.yaml"


class MetaConfigTest(unittest.TestCase):
    def test_current_config_covers_confirmed_semantic_model(self):
        config = load_meta_config(CONFIG_PATH)

        self.assertEqual(config.model.id, "ecommerce")
        self.assertEqual(config.model.version, 1)
        self.assertEqual(config.datasets[0].grain, "one_row_per_order")
        self.assertEqual(config.datasets[0].primary_key, "order_id")
        self.assertEqual(
            {relationship.cardinality for relationship in config.relationships},
            {"many_to_one"},
        )
        self.assertTrue(config.time_dimensions[0].month_filter_requires_year)

        metrics = {metric.id: metric for metric in config.metrics}
        self.assertEqual(
            metrics["order_count"].expression,
            "COUNT(DISTINCT fact_order.order_id)",
        )
        self.assertIn("AOV", metrics["average_quantity_per_order"].aliases)
        self.assertNotIn("GMV", {alias for metric in config.metrics for alias in metric.aliases})

    def test_duplicate_metric_id_is_rejected(self):
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            mapping = yaml.safe_load(config_file)
        mapping = copy.deepcopy(mapping)
        mapping["metrics"].append(copy.deepcopy(mapping["metrics"][0]))

        with self.assertRaises(MetaConfigValidationError):
            MetaConfig.from_mapping(mapping).validate()

    def test_invalid_metric_reference_is_rejected(self):
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            mapping = yaml.safe_load(config_file)
        mapping = copy.deepcopy(mapping)
        mapping["metrics"][-1]["numerator"] = "unknown_metric"

        with self.assertRaises(MetaConfigValidationError):
            MetaConfig.from_mapping(mapping).validate()

    def test_gmv_alias_is_rejected(self):
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            mapping = yaml.safe_load(config_file)
        mapping = copy.deepcopy(mapping)
        mapping["metrics"][0]["aliases"].append("GMV")

        with self.assertRaises(MetaConfigValidationError):
            MetaConfig.from_mapping(mapping).validate()


if __name__ == "__main__":
    unittest.main()
