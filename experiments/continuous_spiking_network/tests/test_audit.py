"""Independent-audit regression tests using small, fully reviewable artifacts."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from experiments.continuous_spiking_network.audit import (
    AuditError,
    aggregate_runs,
    audit_results,
    classification_metrics,
    paired_interval,
    verify_boundary,
    verify_checkpoint,
)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True))


def _checkpoint(directory, spec):
    directory.mkdir(parents=True)
    array = np.array([[1, 2], [3, 4]], dtype=np.float32)
    raw = array.tobytes()
    np.savez_compressed(
        directory / "state_000.npz", bytes=np.frombuffer(raw, dtype=np.uint8)
    )
    manifest = {
        "format": "concatenated_state_v1",
        "config": {
            key: spec[key] for key in ("architecture", "width", "depth", "seed")
        },
        "tensors": [
            {
                "name": "weights",
                "shape": [2, 2],
                "dtype": "<f4",
                "offset": 0,
                "nbytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        ],
        "parts": [
            {"file": "state_000.npz", "sha256": _digest(directory / "state_000.npz")}
        ],
        "extra": {"selected_step": 1},
    }
    _write(directory / "manifest.json", manifest)
    return _digest(directory / "manifest.json")


def _study(root, count=1):
    source, results = root / "source", root / "results"
    source.mkdir()
    results.mkdir()
    plans = []
    for seed in range(count):
        spec = {
            "stage": "mechanism",
            "task": "long_memory",
            "architecture": "hcsn",
            "seed": seed,
            "width": 1,
            "depth": 1,
            "train_size": 4,
            "val_size": 2,
            "test_size": 2,
            "length": 32,
            "updates": 1,
            "batch_size": 2,
            "data_seed": 90,
            "lr": 0.003,
        }
        plans.append({"run_id": f"mechanism/hcsn/seed{seed}", "spec": spec})
    runs_digest = hashlib.sha256(
        json.dumps(plans, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write(source / "PROTOCOL.json", {"runs_sha256": runs_digest})
    (source / "model.py").write_text("# fixed scientific source\n")
    records = {name: _digest(source / name) for name in ("PROTOCOL.json", "model.py")}
    seal = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    _write(source / "SOURCE_SEAL.json", {"files": records, "sha256": seal})
    _write(results / "RUNS.json", {"source_seal": seal, "runs": plans})
    for plan in plans:
        directory = results / plan["run_id"]
        directory.mkdir(parents=True)
        spec = plan["spec"]
        sources = {}
        for split, n in (("train", 4), ("val", 2), ("test", 2)):
            sources[f"{split}_sample_ids"] = np.array(
                [f"{split}:{i}" for i in range(n)]
            )
            sources[f"{split}_group_ids"] = np.array(
                [f"group:{split}:{i}" for i in range(n)]
            )
            sources[f"{split}_audio_source_ids"] = np.array(
                [f"audio:{split}:{i}" for i in range(n)]
            )
        np.savez_compressed(directory / "split_sources.npz", **sources)
        logits, labels = (
            np.array([[2.0, 0.0], [0.0, 2.0]], dtype=np.float32),
            np.array([0, 1]),
        )
        np.savez_compressed(
            directory / "predictions.npz",
            logits=logits,
            labels=labels,
            sample_ids=sources["test_sample_ids"],
            group_ids=sources["test_group_ids"],
        )
        np.savez_compressed(
            directory / "batch_indices.npz", indices=np.array([[0, 0]], dtype=np.int64)
        )
        _write(directory / "DATA.json", {"task": "long_memory"})
        result = {
            "source_seal": seal,
            "spec": spec,
            "test": classification_metrics(logits, labels),
            "split_sources_sha256": _digest(directory / "split_sources.npz"),
            "checkpoint_manifest_sha256": _checkpoint(directory / "checkpoint", spec),
            "checkpoint_reload_max_error": 0,
            "selected_step": 1,
            "history": [{"update": 1, "validation": {"cross_entropy": 0.5}}],
            "parameters": {"total": 4, "frontend": 2, "backbone": 1, "readout": 1},
            "training_examples_seen": 2,
            "unique_training_examples_seen": 1,
            "training_sequence_positions": 64,
            "training_cpu_seconds": 1.0,
            "total_cpu_seconds": 2.0,
        }
        _write(directory / "RESULT.json", result)
    return source, results, results / plans[0]["run_id"]


class AuditTests(unittest.TestCase):
    def test_valid_study_independently_recomputes_metrics_and_exposures(self):
        with tempfile.TemporaryDirectory() as temp:
            source, results, _ = _study(Path(temp))
            audit = audit_results(results, source)
            self.assertEqual(audit["status"], "passed", audit["issues"])
            checked = audit["runs"][0]["audit"]
            self.assertEqual(checked["metrics"]["accuracy"], 1.0)
            self.assertEqual(checked["exposures"]["unique_training_examples_seen"], 1)
            self.assertAlmostEqual(
                checked["metrics"]["cross_entropy"], np.log1p(np.exp(-2))
            )
            self.assertEqual(audit["aggregates"][0]["mean"]["parameters"]["total"], 4)

    def test_tampered_metrics_fail_and_failed_attempt_is_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            source, results, directory = _study(Path(temp))
            record = json.loads((directory / "RESULT.json").read_text())
            record["test"]["accuracy"] = 0.0
            _write(directory / "RESULT.json", record)
            _write(directory / "FAILED.json", {"traceback": "retained failed attempt"})
            audit = audit_results(results, source)
            self.assertEqual(audit["status"], "failed")
            self.assertIn("Reported test accuracy", audit["runs"][0]["error"])
            self.assertEqual(len(audit["failures"]), 1)
            self.assertFalse(audit["failures"][0]["recovered"])

    def test_cross_split_source_leak_is_detected_even_with_updated_npz_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            source, results, directory = _study(Path(temp))
            with np.load(directory / "split_sources.npz") as old:
                arrays = {key: old[key] for key in old.files}
            arrays["test_audio_source_ids"] = arrays["test_audio_source_ids"].astype(
                "<U64"
            )
            arrays["test_audio_source_ids"][0] = arrays["train_audio_source_ids"][0]
            np.savez_compressed(directory / "split_sources.npz", **arrays)
            record = json.loads((directory / "RESULT.json").read_text())
            record["split_sources_sha256"] = _digest(directory / "split_sources.npz")
            _write(directory / "RESULT.json", record)
            audit = audit_results(results, source)
            self.assertEqual(audit["status"], "failed")
            self.assertIn("Cross-split source leakage", audit["runs"][0]["error"])

    def test_checkpoint_byte_tamper_and_unassigned_tail_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "checkpoint"
            digest = _checkpoint(
                directory, {"architecture": "hcsn", "width": 1, "depth": 1, "seed": 0}
            )
            self.assertEqual(
                verify_checkpoint(directory, digest)[
                    "state_elements_including_buffers"
                ],
                4,
            )
            with (directory / "state_000.npz").open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaisesRegex(AuditError, "chunk SHA"):
                verify_checkpoint(directory, digest)

    def test_missing_plan_result_is_incomplete_and_plan_edits_fail_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            source, results, directory = _study(Path(temp), count=2)
            (directory / "RESULT.json").unlink()
            audit = audit_results(results, source)
            self.assertEqual(audit["status"], "incomplete")
            self.assertEqual(len(audit["inventory"]["missing"]), 1)
            inventory = json.loads((results / "RUNS.json").read_text())
            inventory["runs"] = inventory["runs"][1:]
            _write(results / "RUNS.json", inventory)
            self.assertEqual(audit_results(results, source)["status"], "failed")

    def test_source_edit_and_historical_recovered_failure_remain_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            source, results, directory = _study(Path(temp))
            _write(directory / "FAILED.json", {"traceback": "first attempt failed"})
            audit = audit_results(results, source)
            self.assertEqual(audit["status"], "passed_with_recovered_failures")
            self.assertTrue(audit["failures"][0]["recovered"])
            (source / "model.py").write_text("# changed after registration\n")
            self.assertEqual(audit_results(results, source)["status"], "failed")

    def test_paired_student_interval_uses_seed_variation_and_bonferroni_width(self):
        differences = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
        interval = paired_interval(differences)
        margin = 2.7764451051977987 * differences.std(ddof=1) / np.sqrt(5)
        self.assertAlmostEqual(interval["lower"], 0.03 - margin)
        self.assertAlmostEqual(interval["upper"], 0.03 + margin)
        adjusted = paired_interval(differences, 0.9875)
        self.assertLess(adjusted["lower"], interval["lower"])
        self.assertIsNone(paired_interval([0.2])["lower"])

    def test_aggregation_pairs_seeds_and_rejects_unmatched_heldout_sources(self):
        runs = []
        for seed in range(5):
            for architecture in ("hcsn", "ordinary"):
                gain = 0.01 * (seed + 1) if architecture == "hcsn" else 0.0
                runs.append(
                    {
                        "kind": "classification",
                        "spec": {
                            "stage": "mechanism",
                            "task": "synthetic",
                            "architecture": architecture,
                            "width": 8,
                            "depth": 1,
                            "train_size": 64,
                            "length": 32,
                            "seed": seed,
                        },
                        "audit": {
                            "metrics": {
                                "accuracy": 0.7 + gain,
                                "cross_entropy": 0.5 - gain,
                                "brier": 0.2,
                            },
                            "heldout_fingerprint": "fixed",
                            "batch_fingerprint": f"batch:{seed}",
                        },
                        "result": {
                            "training_cpu_seconds": 1.0,
                            "total_cpu_seconds": 2.0,
                            "parameters": {
                                "total": 4,
                                "frontend": 2,
                                "backbone": 1,
                                "readout": 1,
                            },
                        },
                    }
                )
        aggregates, contrasts = aggregate_runs(runs)
        self.assertEqual(len(aggregates), 2)
        accuracy = contrasts[0]["metrics"]["accuracy"]
        self.assertAlmostEqual(accuracy["ci95"]["mean"], 0.03)
        self.assertTrue(accuracy["formal_five_seed_complete"])
        self.assertEqual(
            accuracy["bonferroni_four_comparisons_ci9875"]["confidence"], 0.9875
        )
        runs[0]["audit"]["heldout_fingerprint"] = "different"
        with self.assertRaisesRegex(AuditError, "unmatched heldout"):
            aggregate_runs(runs)

    def test_boundary_first_stop_and_first_observation_charge_are_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            spec = {"architecture": "hcsn", "width": 1, "depth": 1, "seed": 0}
            digest = _checkpoint(directory / "actor_checkpoint", spec)
            odds = np.array([[0.0, 2.0], [0.0, -2.0]], dtype=np.float32)
            arrays = {
                "episode_id": np.array(["id:0", "id:1"]),
                "label": np.array([1, 0]),
                "snr": np.ones(2),
                "cost": np.array([0.01, 0.02]),
                "horizon": np.array([2, 2]),
                "observations": odds / 2,
                "actor_log_odds": odds,
                "bayes_log_odds": odds,
                "remaining_steps": np.array([[1, 0], [1, 0]]),
            }
            metrics = {}
            for arm in ("fixed", "direct", "value", "oracle"):
                for key, value in {
                    "stop_mask": np.array([[False, True], [False, True]]),
                    "stop_index": np.ones(2, dtype=int),
                    "action": np.array([1, 0]),
                    "correct": np.ones(2, dtype=bool),
                    "observations": np.full(2, 2),
                    "total_cost": np.array([0.02, 0.04]),
                    "net_utility": np.array([0.98, 0.96]),
                }.items():
                    arrays[f"{arm}_{key}"] = value
                metrics[arm] = {
                    "accuracy": 1.0,
                    "mean_observations": 2.0,
                    "mean_total_cost": 0.03,
                    "net_utility": 0.97,
                    "cases": 2,
                }
            np.savez_compressed(directory / "episodes_id_000.npz", **arrays)
            result = {
                "actor": {
                    "checkpoint_manifest_sha256": digest,
                    "checkpoint_reload_max_error": 0,
                },
                "first_observation_charged": True,
                "bayes_teacher": False,
                "fixed": {"threshold": 0.75},
                "direct": {
                    "parameters": {
                        "direct_bias": 0.0,
                        "direct_context": [0.0, 0.0, 0.0],
                    }
                },
                "episode_files": [
                    {
                        "file": "episodes_id_000.npz",
                        "sha256": _digest(directory / "episodes_id_000.npz"),
                        "split": "id",
                        "cases": 2,
                    }
                ],
                "metrics": {"id": metrics},
            }
            self.assertEqual(verify_boundary(directory, result)["episodes"], 2)
            arrays["fixed_total_cost"] -= 0.01
            np.savez_compressed(directory / "episodes_id_000.npz", **arrays)
            result["episode_files"][0]["sha256"] = _digest(
                directory / "episodes_id_000.npz"
            )
            with self.assertRaisesRegex(AuditError, "total_cost accounting"):
                verify_boundary(directory, result)


if __name__ == "__main__":
    unittest.main()
