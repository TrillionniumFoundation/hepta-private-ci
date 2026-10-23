"""Exact heterogeneous storage and conservative population-reporting gates."""

import copy
import hashlib
import json
import lzma
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zlib

from population_baselines import measure_exact
from population_aggregate import aggregate, assess_trial
from population_fixtures import dataset, source_digest


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


class PopulationExactBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.data = dataset(1907)

    def tearDown(self):
        self.temporary.cleanup()

    def test_complete_typed_sources_operations_and_actual_exact_storage(self):
        destination = self.directory / "baseline"
        receipt = measure_exact(self.data, destination, write_json)
        self.assertEqual(receipt["typed_operation_exact"], 1.0)
        self.assertEqual(len(receipt["typed_operation_rows"]), 120)
        probes = (
            self.data["retention_final"]
            + self.data["transfer_final"]
            + self.data["ood_final"]
        )
        for probe, row in zip(probes, receipt["typed_operation_rows"], strict=True):
            self.assertEqual(
                (row["probe_id"], row["answer"], row["roots"], row["exact"]),
                (probe["probe_id"], probe["value"], probe["source_roots"], True),
            )
        self.assertTrue(
            all(
                row["answer"] == "unknown"
                for row in receipt["typed_operation_rows"][-24:]
            )
        )
        self.assertFalse(receipt["semantic_projection_available"])
        self.assertTrue(receipt["source_metadata_retained"])
        payload = (destination / "complete_records.json").read_bytes()
        self.assertEqual(json.loads(payload), self.data["sources"])
        self.assertEqual(
            zlib.decompress((destination / "complete_records.zlib9").read_bytes()),
            payload,
        )
        self.assertEqual(
            lzma.decompress((destination / "complete_records.lzma6").read_bytes()),
            payload,
        )
        with sqlite3.connect(destination / "complete_records.sqlite3") as connection:
            recovered = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT payload FROM memory ORDER BY ordinal"
                )
            ]
        self.assertEqual(recovered, self.data["sources"])
        for name, metadata in receipt["measurements"].items():
            actual = (destination / name).read_bytes()
            self.assertEqual(
                (metadata["bytes"], metadata["sha256"], metadata["lossless"]),
                (len(actual), hashlib.sha256(actual).hexdigest(), True),
            )
        best = receipt["smallest_complete_exact_representation"]
        self.assertEqual(
            best["bytes"], min(row["bytes"] for row in receipt["measurements"].values())
        )
        self.assertFalse(receipt["irreducible_entropy_bound_claimed"])

    def test_saved_seed_and_generator_independently_regenerate_full_ledger(self):
        destination = self.directory / "baseline"
        measure_exact(self.data, destination, write_json)
        bundle = (destination / "seed-and-generator.bin").read_bytes()
        self.assertEqual(
            zlib.decompress((destination / "seed-and-generator.zlib9").read_bytes()),
            bundle,
        )
        header_size = int.from_bytes(bundle[:4], "little")
        header = json.loads(bundle[4 : 4 + header_size])
        source = bundle[4 + header_size :]
        self.assertEqual(hashlib.sha256(source).hexdigest(), header["source_sha256"])
        namespace = {"__name__": "retained_fixture_generator"}
        exec(compile(source, "retained-population-fixtures.py", "exec"), namespace)
        regenerated = namespace["dataset"](header["seed"])["sources"]
        self.assertEqual(regenerated, self.data["sources"])

    def test_probe_gold_changes_scoring_but_not_computed_answer(self):
        poisoned = copy.deepcopy(self.data)
        expected = poisoned["retention_final"][0]["value"]
        poisoned["retention_final"][0]["value"] = "unavailable probe gold"
        receipt = measure_exact(poisoned, self.directory / "baseline", write_json)
        first = receipt["typed_operation_rows"][0]
        self.assertEqual(first["answer"], expected)
        self.assertFalse(first["exact"])
        self.assertAlmostEqual(receipt["typed_operation_exact"], 119 / 120)

    def test_generator_cannot_claim_a_stale_digest_for_a_different_actual_ledger(self):
        changed = copy.deepcopy(self.data)
        changed["sources"][0]["value"] = "amber"
        source = changed["sources"][0]
        source["source_digest"] = source_digest(
            {key: value for key, value in source.items() if key != "source_digest"}
        )
        self.assertNotEqual(
            source_digest(changed["sources"]), changed["sources_sha256"]
        )
        with self.assertRaises(ValueError):
            measure_exact(changed, self.directory / "mismatched", write_json)
        self.assertFalse((self.directory / "mismatched").exists())
        changed["sources_sha256"] = source_digest(changed["sources"])
        with self.assertRaises(ValueError):
            measure_exact(changed, self.directory / "different-generator", write_json)
        self.assertFalse((self.directory / "different-generator").exists())


class PopulationAggregateTests(unittest.TestCase):
    def inputs(self, *, single=0.75, split=0.875, metadata=0.75):
        training = {
            "costs": {"same_adapter_budget": True, "total_optimizer_updates": 2560},
            "parent_unchanged": True,
            "source_dependency_groups_preserved": True,
        }
        selection = {
            "choice": {
                "matched_optimizer_updates": True,
                "router_within_one_percent": True,
                "chosen_arm": "split",
                "parent_recall_gate": True,
                "parent_correct_semantic_preserved": {"split": True},
            }
        }
        metrics = {
            "single": {"retention": {"accuracy": single}},
            "split_learned_guarded": {"retention": {"accuracy": split}},
            "oracle": {"retention": {"accuracy": max(0.90625, split)}},
            "uniform_random": {"retention": {"accuracy": 0.5}},
            "split_metadata_only": {"retention": {"accuracy": metadata}},
            "selected": {
                name: {"accuracy": 0.875}
                for name in (
                    "semantic",
                    "episode",
                    "procedure",
                    "event_interpolation",
                    "procedure_extrapolation",
                    "known",
                )
            },
        }
        final = {
            "metrics": metrics,
            "routing": {
                "supported_retention_coverage": 0.9,
                "raw_ood_reject_rate": 0.95,
            },
            "all_owner_admitted": True,
            "selection_unchanged": True,
            "chosen_before_final_read": True,
            "chosen_arm": "split",
            "parent_semantic_recall": 0.875,
            "parent_correct_semantic_preserved": {"split": True},
        }
        codec = {
            "variants": {
                "8": {
                    "storage_ratio_gate": True,
                    "retention_loss_gate": True,
                    "quality_loss": {"retention": 0.0, "transfer": 0.0},
                },
                "4": {
                    "storage_ratio_gate": True,
                    "retention_loss_gate": True,
                    "quality_loss": {"retention": 0.0, "transfer": 0.0},
                },
            },
            "primary_gate_passed": True,
        }
        baseline = {
            "typed_operation_exact": 1.0,
            "smallest_complete_exact_representation": {"bytes": 1000},
        }
        costs = {"retained_data_and_model_lower_bound_bytes": 10000}
        return training, selection, final, codec, baseline, costs

    def trial(self, seed, inputs=None):
        arguments = self.inputs() if inputs is None else inputs
        return {
            "seed": seed,
            "protocol_sha256": "a" * 64,
            "source_identity": {"source_manifest_sha256": "b" * 64},
            "training": arguments[0],
            **assess_trial(*arguments),
        }

    def test_positive_fission_keeps_general_and_net_compression_claims_closed(self):
        result = aggregate([self.trial(seed) for seed in (4051, 1907, 2719)])
        self.assertEqual(result["seeds"], [1907, 2719, 4051])
        self.assertEqual(result["mean_split_retention_gain"], 0.125)
        self.assertTrue(result["claim_gates"]["matched_budget_fission_advantage"])
        self.assertTrue(result["claim_gates"]["bounded_heterogeneous_retention"])
        self.assertTrue(result["claim_gates"]["bounded_heterogeneous_transfer"])
        self.assertFalse(result["claim_gates"]["net_memory_compression_advantage"])
        self.assertFalse(result["claim_gates"]["general_memory"])
        self.assertFalse(result["all_claims_passed"])

    def test_real_reader_boolean_precommit_contract_is_accepted(self):
        arguments = self.inputs()
        report = assess_trial(*arguments)
        self.assertTrue(report["engineering_gates"]["selection_preceded_final_reads"])
        for flag, arm in ((False, "split"), (True, "single"), ("split", "split")):
            with self.subTest(flag=flag, arm=arm):
                arguments[2]["chosen_before_final_read"] = flag
                arguments[2]["chosen_arm"] = arm
                self.assertFalse(
                    assess_trial(*arguments)["engineering_gates"][
                        "selection_preceded_final_reads"
                    ]
                )

    def test_positive_mean_cannot_hide_one_negative_seed(self):
        trials = [
            self.trial(1907, self.inputs(split=0.70)),
            self.trial(2719, self.inputs(split=0.95)),
            self.trial(4051, self.inputs(split=0.95)),
        ]
        result = aggregate(trials)
        self.assertGreater(result["mean_split_retention_gain"], 0.05)
        self.assertFalse(result["claim_gates"]["matched_budget_fission_advantage"])
        self.assertLess(result["per_seed"][0]["summary"]["split_retention_gain"], 0)
        self.assertEqual(len(result["per_seed"]), 3)
        self.assertTrue(result["negative_outcomes_retained"])

    def test_beating_random_does_not_imply_beating_metadata_capability(self):
        trials = [
            self.trial(seed, self.inputs(metadata=0.875)) for seed in (1907, 2719, 4051)
        ]
        result = aggregate(trials)
        self.assertTrue(result["claim_gates"]["bounded_learned_router_vs_random"])
        self.assertFalse(
            result["claim_gates"]["learned_router_advantage_over_metadata"]
        )
        self.assertTrue(
            all(
                row["summary"]["router_gain_over_random"] > 0.05
                for row in result["per_seed"]
            )
        )
        self.assertTrue(
            all(
                row["summary"]["router_gain_over_metadata"] == 0
                for row in result["per_seed"]
            )
        )

    def test_bad_int8_retention_cannot_be_rescued_by_small_bytes_or_int4(self):
        failing = self.inputs()
        failing[3]["variants"]["8"]["quality_loss"]["retention"] = 3 / 64
        failing[3]["variants"]["8"]["retention_loss_gate"] = False
        failing[3]["primary_gate_passed"] = False
        trials = [self.trial(1907, failing), self.trial(2719), self.trial(4051)]
        result = aggregate(trials)
        self.assertTrue(result["engineering_passed"])
        self.assertFalse(result["claim_gates"]["int8_checkpoint_storage_and_quality"])
        self.assertFalse(
            result["per_seed"][0]["research_gates"]["int8_storage_and_quality"]
        )
        self.assertTrue(failing[3]["variants"]["8"]["storage_ratio_gate"])
        self.assertTrue(failing[3]["variants"]["4"]["retention_loss_gate"])

    def test_parent_forgetting_or_owner_failure_blocks_claims(self):
        forgetting = self.inputs()
        forgetting[2]["parent_correct_semantic_preserved"]["split"] = False
        trials = [self.trial(1907, forgetting), self.trial(2719), self.trial(4051)]
        self.assertFalse(
            aggregate(trials)["claim_gates"]["matched_budget_fission_advantage"]
        )
        unadmitted = self.inputs()
        unadmitted[2]["all_owner_admitted"] = False
        trials[0] = self.trial(1907, unadmitted)
        result = aggregate(trials)
        self.assertFalse(result["engineering_passed"])
        self.assertFalse(any(result["claim_gates"].values()))

    def test_missing_duplicate_seeds_or_mixed_source_protocol_are_rejected(self):
        complete = [self.trial(seed) for seed in (1907, 2719, 4051)]
        changed_protocol = copy.deepcopy(complete)
        changed_protocol[-1]["protocol_sha256"] = "c" * 64
        changed_source = copy.deepcopy(complete)
        changed_source[-1]["source_identity"]["source_manifest_sha256"] = "d" * 64
        for trials in (
            complete[:2],
            [complete[0], complete[0], complete[2]],
            changed_protocol,
            changed_source,
        ):
            with (
                self.subTest(seeds=[row["seed"] for row in trials]),
                self.assertRaises(ValueError),
            ):
                aggregate(trials)

    def test_nonfinite_or_out_of_range_measured_metrics_are_rejected(self):
        for invalid in (float("nan"), float("inf"), -0.1, 1.1, True):
            with self.subTest(accuracy=invalid), self.assertRaises(ValueError):
                self.trial(1907, self.inputs(split=invalid))


if __name__ == "__main__":
    unittest.main()
