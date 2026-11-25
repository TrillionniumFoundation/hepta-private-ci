"""Artificial receipts with hand-computable answers; never model performance."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from . import analysis_results as analysis


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hcsn-analysis-artificial-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.training = self.root/"training"
        self.training.mkdir()
        self.protocol = {"experiment_id": "ARTIFICIAL-RECEIPTS-NOT-AN-EXPERIMENT",
            "independent_neurons": [8], "seeds": [1, 2, 3], "arms": [{"id": "qvi_full"}, {"id": "qvi_flow"}],
            "source_hashes": {"artificial": "0"*64}, "runtime": {"python": "fixture"},
            "validation": {"min_final_accuracy": .8, "min_learned_over_initial_accuracy": .1,
                           "min_final_over_pre_late_accuracy": .1, "min_fraction_seeds_passing_learning": 2/3}}
        self.manifest = self.root/"PROTOCOL_FROZEN.json"
        self.write(self.manifest, self.protocol)
        self.digest = analysis.canonical_digest(self.protocol)
        self.results, rows, launches = {}, [], []
        for index, (arm, seed) in enumerate((a, s) for a in self.protocol["arms"] for s in self.protocol["seeds"]):
            name = f'n8-{arm["id"]}-s{seed}'
            directory = self.training/name
            directory.mkdir()
            failed = index == 5
            identity = {"experiment_id": self.protocol["experiment_id"], "protocol_sha256": self.digest,
                        "source_hashes": self.protocol["source_hashes"], "neurons": 8, "arm": arm, "seed": seed, "smoke": False}
            record = {**identity, "status": "failed" if failed else "completed", "error": "fixture failure" if failed else None,
                "selected_step": 0 if index == 2 else 5, "updates": 5, "attempted_updates": 5,
                "training_cpu_seconds": index+1, "training_cpu_overrun": 0.,
                "cost": {"cpu_seconds": index+1.5, "wall_seconds": index+2., "process_max_rss_kib": 100+index}}
            self.results[name] = record
            self.write(directory/"result.json", record)
            self.write(directory/"worker_cost.json", {"status": record["status"],
                "process_cpu_through_report_seconds": index+2., "wall_including_import_seconds": index+3.,
                "process_peak_rss_bytes": 1024*(101+index)})
            launches.append({"attempt": name, "returncode": int(failed), "launch_through_exit_wall_seconds": index+10.})
            if failed:
                rows.append({"attempt": name, "status": "unavailable", "reason": "fixture failure"})
                continue
            accuracy = (.9, .85, .5, .8, .8)[index]
            initial = .5 if index == 2 else .6
            pre_late = (.7, .65, .5, .6, .6)[index]
            metrics = {"accuracy": accuracy, "brier": (.2, .3, .5, .25, .3)[index], "cross_entropy": .5,
                "pre_late_accuracy": pre_late, "stopping_utility": .4, "maximum_chunk_state_tensor_bytes": 256,
                "source_accuracy": {"300": accuracy-.02, "301": accuracy+.02}}
            self.write(directory/"test_predictions.json", {"artificial_hash_fixture_only": True, "attempt": name})
            row = {"attempt": name, "status": "evaluated", "neurons": 8, "arm": arm["id"], "seed": seed,
                "selected_step": record["selected_step"], "metrics": metrics, "initial_metrics": {"accuracy": initial},
                "data_sha256": "artificial-common-data", "predictions_sha256": self.hash(directory/"test_predictions.json"),
                "cost": {"cpu_seconds": .1, "wall_seconds": .2}}
            self.write(directory/"test_result.json", row)
            rows.append(row)
        self.write(self.training/"SHARD_n8.json", {"neurons": 8, "workers": 2, "attempts": launches,
            "shard_wall_seconds": 60., "all_child_cpu_seconds_including_shutdown": 28., "driver_cpu_seconds": .2})
        seal = {"protocol_sha256": self.digest, "source_hashes": self.protocol["source_hashes"],
                "attempts": {name: self.hash(self.training/name/"result.json") for name in self.results}}
        self.write(self.training/"SEAL.json", seal)
        self.write(self.training/"FINAL_RESULTS.json", {"experiment_id": self.protocol["experiment_id"],
            "protocol_sha256": self.digest, "seal_sha256": self.hash(self.training/"SEAL.json"), "results": rows})

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, sort_keys=True))

    @staticmethod
    def hash(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_known_gates_pairing_failure_costs_and_source_hierarchy(self):
        report = analysis.build_summary(self.manifest, self.training)
        full, flow = report["groups"]
        self.assertAlmostEqual(full["metrics"]["accuracy"]["mean"], .75)
        self.assertAlmostEqual(full["metrics"]["accuracy"]["sample_std"], .0475**.5)
        self.assertEqual((full["learning_passing_seeds"], full["selected_step_zero_evaluated"]), (2, 1))
        self.assertEqual((flow["evaluated_seeds"], flow["expected_seeds"], flow["failed_training_seeds"]), (2, 3, 1))
        self.assertTrue(flow["learning_group_pass"])
        pair = report["paired_comparisons"][0]
        self.assertEqual((pair["paired_seeds"], pair["missing_seed_pairs"]), (2, [3]))
        self.assertAlmostEqual(pair["difference"]["accuracy"]["mean"], .075)
        self.assertEqual(report["costs"]["training_attempt_totals"]["training_cpu_seconds"]["sum"], 21)
        self.assertEqual(report["costs"]["training_attempt_totals"]["worker_cpu_seconds"]["sum"], 27)
        self.assertEqual(full["source_granularity"]["source_count"], 2)
        self.assertIsNone(report["costs"]["campaign_elapsed_makespan_seconds"])

    def test_tampered_receipt_is_not_summarized(self):
        name = next(iter(self.results))
        altered = deepcopy(self.results[name])
        altered["selected_step"] = 999
        self.write(self.training/name/"result.json", altered)
        with self.assertRaisesRegex(ValueError, "sealed training result changed"):
            analysis.build_summary(self.manifest, self.training)

    def test_missing_predictions_prevent_pass_and_seal_is_required(self):
        (self.training/"n8-qvi_full-s3/test_predictions.json").unlink()
        report = analysis.build_summary(self.manifest, self.training)
        full = report["groups"][0]
        self.assertEqual(full["learning_passing_seeds"], 2)
        self.assertFalse(full["learning_group_pass"])
        self.assertEqual(full["learning_group_status"], "UNVERIFIED")
        (self.training/"SEAL.json").unlink()
        with self.assertRaises(FileNotFoundError):
            analysis.build_summary(self.manifest, self.training)

    def test_cli_is_stdlib_read_only_and_outputs_are_create_only(self):
        before = {str(p): self.hash(p) for p in self.training.rglob("*.json")}
        command = [sys.executable, str(Path(analysis.__file__)), "--protocol", str(self.manifest),
                   "--training", str(self.training), "--output-dir", str(self.root/"analysis")]
        first = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue((self.root/"analysis/RESULTS_TRAINING.md").exists())
        second = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(before, {str(p): self.hash(p) for p in self.training.rglob("*.json")})


if __name__ == "__main__":
    unittest.main()
