import ast
import json
from pathlib import Path
import subprocess
import sys
import unittest

from shared_cell_budget_experiment import (
    AUTHORITY,
    PROTOCOL_MODE,
    build_feature_cache,
    run_experiment,
)


class SharedCellBudgetExperimentTests(unittest.TestCase):
    def test_equal_flop_budget_and_frozen_cache(self):
        result = run_experiment(seed=17)
        arms = {arm["architecture"]: arm for arm in result["arms"]}
        self.assertEqual(set(arms), {"shared_head", "per_cell_light_head"})
        self.assertTrue(result["budget"]["budget_is_equal_across_arms"])
        self.assertEqual(arms["shared_head"]["train_flops"], arms["per_cell_light_head"]["train_flops"])
        self.assertEqual(arms["shared_head"]["train_flops"], result["budget"]["train_flops"])
        self.assertEqual(arms["shared_head"]["train_budget_flops"], result["budget"]["train_flops"])
        self.assertEqual(arms["per_cell_light_head"]["train_budget_flops"], result["budget"]["train_flops"])
        self.assertLess(arms["shared_head"]["parameter_count"], arms["per_cell_light_head"]["parameter_count"])
        self.assertEqual(arms["shared_head"]["cache_digest"], arms["per_cell_light_head"]["cache_digest"])
        self.assertTrue(result["encoder"]["frozen"])
        self.assertTrue(result["encoder"]["same_cache_for_all_arms"])

    def test_metrics_are_bounded_and_protocol_is_shadow_only(self):
        result = run_experiment(seed=17)
        self.assertEqual(result["protocol"]["mode"], PROTOCOL_MODE)
        self.assertEqual(result["protocol"]["authority"], AUTHORITY)
        self.assertFalse(result["protocol"]["production_caller"])
        self.assertFalse(result["protocol"]["model_invocation"])
        self.assertFalse(result["protocol"]["provider_dispatch"])
        for arm in result["arms"]:
            self.assertEqual(arm["mode"], "SHADOW_ONLY")
            self.assertEqual(arm["authority"], "DENY_ALL")
            self.assertGreaterEqual(arm["future_utility"], 0.0)
            self.assertLessEqual(arm["future_utility"], 1.0)
            self.assertGreaterEqual(arm["cross_dataset_utility"], 0.0)
            self.assertLessEqual(arm["cross_dataset_utility"], 1.0)
            self.assertGreaterEqual(arm["wrong_routing_rate"], 0.0)
            self.assertLessEqual(arm["wrong_routing_rate"], 1.0)
            self.assertGreaterEqual(arm["old_task_degradation"], 0.0)

    def test_same_seed_is_reproducible_and_cache_is_identical(self):
        self.assertEqual(run_experiment(seed=17), run_experiment(seed=17))
        first = build_feature_cache(seed=17)
        second = build_feature_cache(seed=17)
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.old_train, second.old_train)
        self.assertNotEqual(run_experiment(seed=17), run_experiment(seed=18))

    def test_no_external_ml_imports(self):
        source_path = Path(__file__).with_name("shared_cell_budget_experiment.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue({"torch", "tensorflow", "jax", "numpy", "pandas"}.isdisjoint(imported_roots))

    def test_cli_emits_json(self):
        source_path = Path(__file__).with_name("shared_cell_budget_experiment.py")
        completed = subprocess.run(
            [sys.executable, str(source_path), "--seed", "17"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["seed"], 17)
        self.assertEqual(len(payload["arms"]), 2)
        self.assertEqual(payload["protocol"]["mode"], "SHADOW_ONLY")


if __name__ == "__main__":
    unittest.main()
