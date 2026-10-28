"""Measured candidate training and coherent parameter-generation checks."""

import hashlib
import json
import tempfile
from pathlib import Path
import unittest

from v6.cells import canonical
from v6.evolution import CellEnsemble, EvolutionController, partitions
from v6.learning import run_learning_study


def records(count=16):
    return [
        {
            "key": f"item-{i}",
            "value": {"factor": i % 4 + 1, "label": f"group-{i % 4}"},
            "event_id": f"event-{i}",
            "kind": "semantic",
        }
        for i in range(count)
    ]


class EvolutionTests(unittest.TestCase):
    def test_real_split_merge_candidates_are_charged_and_parent_is_unchanged(self):
        data = records()
        keys, values = [row["key"] for row in data], [row["value"] for row in data]
        parent = CellEnsemble.fit(data, partitions(keys, 4, 11), seed=11, steps=150)
        old_bytes = parent.to_bytes()
        controller = EvolutionController(steps=150)
        child, receipt = controller.propose(
            data,
            keys[::2],
            values[::2],
            parent=parent,
            seed=11,
            retention_keys=keys[1::4],
            retention_values=values[1::4],
        )
        self.assertEqual(parent.to_bytes(), old_bytes)
        self.assertIsNotNone(child)
        self.assertEqual(child.generation, parent.generation + 1)
        candidates = {row["name"]: row for row in receipt["candidates"]}
        self.assertTrue({"fixed_2", "fixed_4", "split", "merge", "keep", "refit"} <= set(candidates))
        self.assertGreater(candidates["split"]["training_work_proxy"], 0)
        self.assertGreater(candidates["merge"]["training_work_proxy"], 0)
        self.assertEqual(
            receipt["all_candidate_retained_bytes"], sum(len(raw) for raw in controller.candidate_artifacts.values())
        )
        self.assertTrue(all(child.read(key)["value"] == value for key, value in zip(keys[3::4], values[3::4])))
        self.assertFalse(receipt["equal_parameter_counts_claimed"])
        self.assertEqual(candidates["split"]["retention"]["rows"], len(keys[1::4]))
        self.assertTrue(receipt["evaluation_split"]["retention_from_parent_support"])
        with self.assertRaisesRegex(ValueError, "independent"):
            controller.propose(
                data, keys[:2], values[:2], parent=parent, retention_keys=keys[:2], retention_values=values[:2]
            )

    def test_search_cost_and_equal_parameter_ceiling_are_enforced(self):
        data = records(20)
        keys, values = [row["key"] for row in data], [row["value"] for row in data]
        parent = CellEnsemble.fit(data, partitions(keys, 4, 29), seed=29, steps=200)
        budget = 4 * (64 * (64 + 4 + 1) + 4)
        controller = EvolutionController(
            steps=200, parameter_budget_bytes=budget, expected_future_queries=1, inference_work_price=0
        )
        _, receipt = controller.propose(
            data, keys[:6], values[:6], parent=parent, seed=29, retention_keys=keys[6:12], retention_values=values[6:12]
        )
        self.assertTrue(all(row["cost"]["parameter_bytes"] <= budget for row in receipt["candidates"]))
        self.assertTrue(
            all(
                row["parameter_budget_slack_bytes"] == budget - row["cost"]["parameter_bytes"]
                for row in receipt["candidates"]
            )
        )
        comparison = receipt["forecast_cost_comparison"]
        self.assertGreater(
            comparison["adaptive_all_search_upfront"], comparison["baseline_optimistic_single_fit_upfront"]
        )
        self.assertLess(comparison["projected_net_benefit"], 0)
        self.assertIsNone(comparison["break_even_queries"])
        self.assertFalse(receipt["structural_adoption_approved"])
        self.assertIn(receipt["selected"], {"refit", "fixed_2", "fixed_4"})

    def test_budget_rejection_keeps_negative_results(self):
        data = records(8)
        controller = EvolutionController(maximum_bytes=10, steps=100)
        child, receipt = controller.propose(data, [row["key"] for row in data[:4]], [row["value"] for row in data[:4]])
        self.assertIsNone(child)
        self.assertTrue(all(not row["eligible"] for row in receipt["candidates"]))
        self.assertGreater(receipt["all_candidate_work_proxy"], 0)
        self.assertEqual(len(controller.candidate_artifacts), 3)

    def test_sleep_releases_arrays_and_read_reloads_exact_immutable_model(self):
        data = records(12)
        keys = [row["key"] for row in data]
        model = CellEnsemble.fit(data, partitions(keys, 2, 3), seed=3, steps=150)
        expected = [model.read(key) for key in keys]
        before = model.to_bytes()
        model.sleep()
        self.assertEqual(model.cost()["loaded_parameter_bytes"], 0)
        self.assertGreater(model.cost()["serialized_cache_bytes"], 0)
        self.assertEqual([model.read(key) for key in keys], expected)
        self.assertEqual(model.reload_count, 2)
        self.assertEqual(model.to_bytes(), before)

    def test_route_tamper_rejected_even_with_rehashed_envelope(self):
        data = records(8)
        model = CellEnsemble.fit(data, partitions([row["key"] for row in data], 2, 5), seed=5, steps=100)
        raw = json.loads(model.to_bytes())
        first = next(iter(raw["payload"]["routes"]))
        raw["payload"]["routes"][first] = 1 - raw["payload"]["routes"][first]
        raw["sha256"] = hashlib.sha256(canonical(raw["payload"])).hexdigest()
        with self.assertRaisesRegex(ValueError, "route inventory"):
            CellEnsemble.from_bytes(canonical(raw))

    def test_end_to_end_study_retains_source_models_costs_and_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "development"
            report = run_learning_study(103, output)
            self.assertTrue(report["counterfactual"]["changed_correctly"])
            self.assertTrue(report["independent_clean_refit_same_parameters"])
            self.assertEqual(report["deleted_read"]["abstain"], "outside-written-support")
            self.assertEqual(report["surviving"]["correct"], report["surviving"]["rows"])
            self.assertEqual(report["procedure"]["correct"], report["procedure"]["rows"])
            self.assertEqual(report["composition"]["correct"], len(report["composition"]["rows"]))
            self.assertFalse(report["general_memory_claim"])
            self.assertFalse(
                set(report["structure_tests"]["selection_keys"]) & set(report["structure_tests"]["test_keys"])
            )
            self.assertFalse(
                set(report["structure_tests"]["retention_keys"]) & set(report["structure_tests"]["test_keys"])
            )
            self.assertTrue(report["no_replay"]["matched_catalog"])
            self.assertTrue(report["no_replay"]["matched_initial_parameters"])
            self.assertTrue(report["evolved_structure"]["evaluation_split"]["retention_from_parent_support"])
            self.assertIsNotNone(report["equal_parameter_structure"]["equal_parameter_byte_ceiling"])
            self.assertTrue(report["structure_tests"]["frozen_cost_comparison"]["all_search_upfront_included"])
            self.assertFalse(report["structure_tests"]["frozen_cost_comparison"]["selection_changed_after_test"])
            self.assertTrue((output / "structure-evolved-split.ensemble.json").is_file())
            self.assertTrue((output / "structure-evolved-merge.ensemble.json").is_file())
            manifest = json.loads((output / "MANIFEST.json").read_bytes())
            self.assertEqual(
                set(manifest["files"]), {path.name for path in output.iterdir() if path.name != "MANIFEST.json"}
            )


if __name__ == "__main__":
    unittest.main()
