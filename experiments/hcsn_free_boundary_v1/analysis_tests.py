"""Synthetic-fixture tests; no main-study outcome is opened by this suite."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .analysis import (IncompleteStudyError, aggregate_strata, analyze, data_strata,
                       descriptive, digest, holm_adjust, inspect_run,
                       mechanism_comparisons, paired_interval, require_complete,
                       selected_parameter_audit, sign_flip_test,
                       validate_prediction_archive, verify_pairing, BASELINES)
from .analysis_secondary import choose_128_candidate


def protocol_fixture():
    contrasts = ["fixed_dual", "direct_dual", "free_margin", "free_continuation", "free_ordinary", "two_gates"]
    return dict(study_id="synthetic_fixture", core=dict(tasks=["task_a", "task_b"],
                models=["free_dual", "two_gates"], seeds=[1, 2, 3]),
                mechanism=dict(tasks=["task_a", "task_b"], models=["free_dual"] + contrasts, seeds=list(range(1, 9))),
                statistics=dict(mechanism_contrasts=contrasts, alpha=0.05, minimum_mean_advantage=0.01),
                optimization=dict(width=32, depth=1, batch_size=32, max_updates=8192,
                                  training_cpu_seconds_per_lr=20.0, learning_rates=[0.001, 0.003], evaluation_batch_size=128))


def complete_metric_runs(protocol):
    runs = {}
    for task in protocol["mechanism"]["tasks"]:
        for model in protocol["mechanism"]["models"]:
            for seed in protocol["mechanism"]["seeds"]:
                runs[(task, model, seed)] = dict(status="valid", metrics={"test": {"accuracy": 0.8 if model == "free_dual" else 0.75}})
    return runs


def save_prediction_fixture(path, labels, row_order=None):
    samples, steps = np.nonzero(labels != -100)
    if row_order is not None:
        samples, steps = samples[row_order], steps[row_order]
    target = labels[samples, steps]
    classes = int(target.max()) + 1
    logits = np.zeros((len(target), classes), dtype=np.float32)
    logits[np.arange(len(target)), target] = 3
    np.savez_compressed(path, logits=logits, predictions=logits.argmax(-1), labels=target,
                        supervised=labels != -100, sample_indices=samples, step_indices=steps)
    return validate_prediction_archive(path, labels, classes)[0]


def create_run_fixture(directory, protocol):
    """Complete numeric checkpoint/selection/log fixture, independent of Torch."""
    directory.mkdir(parents=True)
    labels = np.array([[-100, 0], [1, -100]], dtype=np.int64)
    dataset = dict(sha256="fixture_data_hash", labels={"test": labels}, manifest={"output_dim": 2})
    names = ["frontend.weight", "layers.0.mu_bias", "layers.0.raw_K", "layers.0.raw_reset_gap", "layers.0.raw_refractory"]
    groups = ("content", "dynamics", "boundary", "reset", "refractory")
    initial = {name: np.zeros(1, dtype=np.float64) for name in names}
    initial["layers.0.fixed_boundary"] = np.ones(1)
    candidates = []
    counts = dict(total=5, frontend=1, backbone=4, readout=0, groups={name: 1 for name in groups})
    for index, lr in enumerate(protocol["optimization"]["learning_rates"]):
        target = directory / f"lr_{index}_{lr:g}"
        target.mkdir()
        np.savez_compressed(target / "initial.npz", **initial)
        shifted = {name: (array.copy() if name.endswith("fixed_boundary") else array + 0.1) for name, array in initial.items()}
        np.savez_compressed(target / "step_000001.npz", **shifted)
        checkpoint = dict(step=1, weights="step_000001.npz", sha256=digest(target / "step_000001.npz"),
                          training_cpu_seconds=20.1, crossed_cpu_targets=[5.0, 10.0, 20.0], fixed_step_128=False,
                          validation=dict(cross_entropy=0.6 + index * 0.1, accuracy=0.5),
                          primary_eligible=True, endpoint_overrun_seconds=0.1)
        record = dict(step=1, loss=0.7, training_cpu_seconds=20.1, batch_sha256="b" * 64,
                      prefix_sha256="p" * 64, preclip_gradient_l2=0.5,
                      gradients={name: dict(l2=0.2, max_abs=0.2, missing_elements=0, finite=True) for name in groups})
        (target / "updates.jsonl").write_text(json.dumps(record) + "\n")
        candidate = dict(model="free_dual", seed=1, learning_rate=lr, config={}, counts=counts,
                         requested_training_cpu_seconds=20.0, training_cpu_seconds=20.1, updates=1,
                         setup_cpu_seconds=0.2, validation_cpu_seconds=0.2, total_cpu_seconds=20.8,
                         initial_sha256=digest(target / "initial.npz"), batch_prefix_sha256="p" * 64,
                         first128_prefix_sha256=None, checkpoints=[checkpoint], best=checkpoint,
                         selected_parameter_changes={name: dict(l2=0.1, max_abs=0.1) for name in groups})
        (target / "candidate.json").write_text(json.dumps(candidate))
        candidates.append(dict(candidate, directory=target.name))
    winner = candidates[0]
    (directory / "selected.npz").write_bytes((directory / winner["directory"] / winner["best"]["weights"]).read_bytes())
    selection = dict(rule="minimum_validation_cross_entropy_only", selected_learning_rate=winner["learning_rate"],
                     selected_step=1, selected_validation=winner["best"]["validation"],
                     selected_checkpoint_sha256=winner["best"]["sha256"], completed_lr_candidates=2,
                     dataset_sha256=dataset["sha256"])
    metrics = save_prediction_fixture(directory / "test_predictions.npz", labels)
    request = dict(model="free_dual", seed=1, cpu_seconds=20.0, width=32, depth=1, batch_size=32,
                   max_updates=8192, learning_rates=[0.001, 0.003])
    summary = dict(request=request, selection=selection, candidates=candidates, counts=counts,
                   selected_model_config={}, holdout=dict(test=metrics, ood=None), status="completed",
                   holdout_cpu_seconds=0.4, total_cpu_seconds=44.0,
                   access_log=[dict(event="load_split", split="train"), dict(event="load_split", split="val"),
                               dict(event="selection_locked", completed_lr_candidates=2),
                               dict(event="load_split", split="test")])
    (directory / "selection.json").write_text(json.dumps(selection))
    (directory / "summary.json").write_text(json.dumps(summary))
    (directory / "EXECUTION.json").write_text(json.dumps(dict(status="completed", returncode=0,
              child_cpu_seconds=46.0, wall_seconds=50.0, whole_child_peak_rss_bytes=1000000)))
    return dataset


class AnalysisTests(unittest.TestCase):
    def test_sign_flip_minimum_and_zero_effect(self):
        positive = sign_flip_test([0.01] * 8)
        self.assertEqual(positive["p_value"], 2 / 256)
        self.assertEqual(positive["permutations"], 256)
        self.assertEqual(sign_flip_test([0.01, -0.01] * 4)["p_value"], 1)
        self.assertEqual(sign_flip_test([0.0] * 8)["p_value"], 1)

    def test_holm_known_example_and_full_family(self):
        np.testing.assert_allclose(holm_adjust([0.01, 0.04, 0.03, 0.2]), [0.04, 0.09, 0.09, 0.2])
        np.testing.assert_allclose(holm_adjust([2 / 256] * 5 + [1.0]), [6 * 2 / 256] * 5 + [1.0])

    def test_mechanism_seed_units_effect_and_missing_gate(self):
        protocol = protocol_fixture()
        runs = complete_metric_runs(protocol)
        result = mechanism_comparisons(protocol, runs)
        self.assertTrue(all(row["accepted"] for row in result))
        self.assertTrue(all(len(row["seed_pairs"]) == 8 for row in result))
        runs[("task_b", "fixed_dual", 1)]["status"] = "failed"
        failed = mechanism_comparisons(protocol, runs)
        self.assertEqual(failed[0]["status"], "incomplete")
        self.assertFalse(failed[0]["accepted"])
        self.assertIsNone(failed[0]["test"])
        self.assertEqual(len(failed[0]["seed_pairs"]), 7)
        self.assertEqual(failed[1]["holm_adjusted_p"], 6 * 2 / 256)
        self.assertFalse(any(row["accepted"] for row in mechanism_comparisons(protocol, runs, global_gate=False)))

    def test_tasks_are_equally_averaged_within_seed(self):
        protocol = protocol_fixture()
        runs = complete_metric_runs(protocol)
        for seed in protocol["mechanism"]["seeds"]:
            runs[("task_a", "free_dual", seed)]["metrics"]["test"]["accuracy"] = 0.9
            runs[("task_a", "fixed_dual", seed)]["metrics"]["test"]["accuracy"] = 0.8
            runs[("task_b", "free_dual", seed)]["metrics"]["test"]["accuracy"] = 0.4
            runs[("task_b", "fixed_dual", seed)]["metrics"]["test"]["accuracy"] = 0.6
        row = mechanism_comparisons(protocol, runs)[0]
        self.assertAlmostEqual(row["paired_interval"]["mean"], -0.05)
        self.assertFalse(row["accepted"])
        self.assertEqual(row["test"]["p_value"], 2 / 256)

    def test_completion_guard_precedes_any_outcome_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(IncompleteStudyError):
                analyze(root, root / "no_data", root / "no_protocol")
            self.assertIsNone(require_complete(root, partial=True))
            (root / "COMPLETE.json").write_text('{"finished_searches": 0}')
            self.assertEqual(require_complete(root)["finished_searches"], 0)

    def test_supervised_metric_mapping_allows_explicit_row_permutation(self):
        labels = np.array([[-100, 1, 0], [2, -100, 1]], dtype=np.int64)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "predictions.npz"
            metrics = save_prediction_fixture(path, labels, np.array([3, 0, 2, 1]))
            self.assertEqual(metrics["correct"], 4)
            self.assertEqual(metrics["supervised_positions"], 4)
            with np.load(path, allow_pickle=False) as archive:
                arrays = {k: archive[k] for k in archive.files}
            arrays["sample_indices"][0] = arrays["sample_indices"][1]
            arrays["step_indices"][0] = arrays["step_indices"][1]
            np.savez_compressed(path, **arrays)
            with self.assertRaisesRegex(ValueError, "exactly once"):
                validate_prediction_archive(path, labels, 3)

    def test_common_update_prefix_ignores_only_unshared_suffix(self):
        base = dict(task="a", seed=1, lr=0.001, shared_initial_sha256="same", log_sha256="log")
        first = dict(base, model="x", updates=[(1, "a", "aa"), (2, "b", "bb"), (3, "c", "cc")])
        second = dict(base, model="y", updates=[(1, "a", "aa"), (2, "b", "bb")])
        result = verify_pairing([first, second])[0]
        self.assertTrue(result["paired_minibatches_verified"])
        self.assertEqual(result["common_updates"], 2)
        second["updates"][1] = (2, "wrong", "wrong")
        result = verify_pairing([first, second])[0]
        self.assertFalse(result["paired_minibatches_verified"])
        self.assertEqual(result["mismatches"][0]["first_mismatched_update"], 2)

    def test_strata_follow_sample_coordinates_not_prediction_row_number(self):
        metadata = dict(speakers=["speaker_a", "speaker_b"], query_modalities=["image", "spoken"],
                        image_labels=[1, 3], audio_labels=[1, 2],
                        audio_source_ids=["a.wav", "b.wav"], image_source_ids=["i1", "i2"])
        predictions = dict(samples=np.array([1, 0, 1, 0]), correct=np.array([True, False, True, True]))
        rows = data_strata("task_a", "free_dual", 1, "test", predictions, metadata)
        lookup = {(r["stratum"], r["value"]): r for r in rows}
        self.assertEqual(lookup[("query_modality", "image")]["accuracy"], 0.5)
        self.assertEqual(lookup[("query_modality", "spoken")]["accuracy"], 1.0)
        self.assertEqual(lookup[("distractor_digit_agreement", "disagree")]["unique_recordings"], 1)
        aggregation = aggregate_strata(protocol_fixture(), rows)
        self.assertTrue(all(not row["complete"] for row in aggregation["mechanism"]))

    def test_exact128_selection_never_uses_nearby_checkpoint_or_primary_winner(self):
        candidates = [dict(learning_rate=lr, directory=str(lr), checkpoints=[
            dict(step=127, fixed_step_128=False, validation={"cross_entropy": 0.01}),
            dict(step=128, fixed_step_128=True, validation={"cross_entropy": score})])
            for lr, score in ((0.001, 0.8), (0.003, 0.7))]
        result = choose_128_candidate(candidates, [0.001, 0.003])
        self.assertEqual(result["selected"]["learning_rate"], 0.003)
        candidates[1]["checkpoints"].pop()
        result = choose_128_candidate(candidates, [0.001, 0.003])
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["selected"])

    def test_complete_run_integrity_and_independent_parameter_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            protocol = protocol_fixture()
            dataset = create_run_fixture(directory, protocol)
            entry, prefixes, predictions, trainability = inspect_run(directory, "task_a", "free_dual", 1, protocol, dataset)
            self.assertEqual(entry["status"], "valid", entry["errors"])
            self.assertEqual(entry["costs"]["complete_child_cpu_seconds"], 46.0)
            self.assertEqual(entry["costs"]["outside_search_function_cpu_seconds"], 2.0)
            self.assertTrue(trainability["all_groups_passed"])
            self.assertEqual(len(prefixes), 2)
            self.assertEqual(len(predictions["test"]["samples"]), 2)
            with (directory / "selected.npz").open("ab") as stream:
                stream.write(b"identity-changing-bytes")
            invalid = inspect_run(directory, "task_a", "free_dual", 1, protocol, dataset)[0]
            self.assertEqual(invalid["status"], "invalid")
            self.assertIn("checkpoint hash", invalid["errors"][0]["message"])

    def test_failed_run_preserves_process_cost(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "failure.json").write_text('{"error": "synthetic failure"}')
            (directory / "EXECUTION.json").write_text('{"status": "failed", "returncode": 1, "child_cpu_seconds": 7.5}')
            row = inspect_run(directory, "task", "free_dual", 1, protocol_fixture(), {})[0]
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["execution_receipt"]["child_cpu_seconds"], 7.5)

    def test_end_to_end_incomplete_report_keeps_all_declared_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            study, data = root / "study", root / "data"
            study.mkdir()
            data.mkdir()
            protocol = protocol_fixture()
            protocol["core"]["models"] = ["free_dual", *BASELINES]
            protocol_path = root / "PROTOCOL.json"
            protocol_path.write_text(json.dumps(protocol))
            (study / "COMPLETE.json").write_text('{"finished_searches": 1, "scheduled_searches": 1}')
            for task in ("task_a", "task_b"):
                labels = np.array([[-100, 0], [1, -100]], dtype=np.int64)
                path = data / f"{task}.npz"
                np.savez_compressed(path, train_y=labels, val_y=labels, test_y=labels)
                manifest = dict(task=task, sha256=digest(path), output_dim=2, limitations=["synthetic fixture"],
                                splits={split: {"episode_ids": [f"{split}:0", f"{split}:1"]} for split in ("train", "val", "test")})
                path.with_suffix(".json").write_text(json.dumps(manifest))
            directory = study / "runs/task_a/free_dual/1"
            create_run_fixture(directory, protocol)
            data_hash = digest(data / "task_a.npz")
            for filename in ("selection.json", "summary.json"):
                content = json.loads((directory / filename).read_text())
                (content if filename == "selection.json" else content["selection"])["dataset_sha256"] = data_hash
                (directory / filename).write_text(json.dumps(content))
            result = analyze(study, data, protocol_path)
            self.assertEqual(result["valid_searches"], 1)
            self.assertGreater(result["expected_searches"], 1)
            self.assertFalse(result["global_integrity_gate"])
            self.assertEqual(result["primary_acceptance_count"], 0)
            self.assertFalse(result["all_content_screens_passed"])
            for filename in ("ANALYSIS.json", "CORE_TABLE.csv", "MECHANISM_TABLE.csv", "TRAINABILITY.json", "DATA_STRATA.json"):
                self.assertTrue((study / "analysis001" / filename).is_file())
            with self.assertRaises(FileExistsError):
                analyze(study, data, protocol_path)


if __name__ == "__main__":
    unittest.main()
