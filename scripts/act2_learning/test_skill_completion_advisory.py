"""Projection/math controls; synthetic optimizer steps are not qualified probe fits."""

import copy
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from ensure_transition_loader import PINS, load_transitions
from skill_completion_advisory import CompletionAdvisor, _data, _parameter_digest
from skill_completion_advisory import _plan, _scores, run_probe


def archive():
    return Path(
        os.environ.get(
            "ACT_TEST_ARCHIVE",
            Path(__file__).resolve().parents[2]
            / "qualification/act2-learning-20261110/run2",
        )
    )


def synthetic_features():
    return np.array(
        [
            [1, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            [1, 0, 1, 0, 1, 0, 0, 0, 0, 1],
            [1, 0, 0, 0, 1, 0, 0, 0.5, 0, 1],
        ],
        dtype=np.float64,
    )


class SkillCompletionAdvisoryTests(unittest.TestCase):
    def test_backprop_matches_finite_difference_for_every_parameter_family(self):
        model = CompletionAdvisor(91)
        x, y = synthetic_features(), np.array([0.0, 1.0, 1.0])
        _, _, gradients = model.loss_gradient(x, y)
        for key, value in model.parameters.items():
            with self.subTest(parameter=key):
                index = (0,) * value.ndim
                original = value[index]
                value[index] = original + 1e-6
                upper = model.loss_gradient(x, y)[0]
                value[index] = original - 1e-6
                lower = model.loss_gradient(x, y)[0]
                value[index] = original
                self.assertAlmostEqual(
                    (upper - lower) / 2e-6, gradients[key][index], delta=1e-7
                )
        bad = x.copy()
        bad[0, 1] = 1
        with self.assertRaisesRegex(ValueError, "incomplete ensure-entry"):
            model.predict(bad)

    def test_synthetic_optimizer_steps_change_parameters_and_roundtrip(self):
        x, y = synthetic_features(), np.array([0.0, 1.0, 1.0])
        model = CompletionAdvisor(92)
        before = _parameter_digest(model.parameters)
        initial = model.loss_gradient(x, y)[1]
        records = model.fit(x, y, steps=30)
        self.assertEqual([r["step"] for r in records], list(range(1, 31)))
        self.assertEqual(records[0]["parameters_before_sha256"], before)
        self.assertEqual(
            records[-1]["parameters_after_sha256"], _parameter_digest(model.parameters)
        )
        self.assertTrue(
            all(r["parameter_bytes_changed"] and r["update_l2"] > 0 for r in records)
        )
        self.assertNotEqual(before, _parameter_digest(model.parameters))
        self.assertLess(model.loss_gradient(x, y)[1], initial)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic-control.npz"
            np.savez(path, **model.parameters)
            restored = CompletionAdvisor(0)
            with np.load(path, allow_pickle=False) as weights:
                restored.parameters = {
                    key: weights[key].copy() for key in restored.parameters
                }
            self.assertEqual(
                _parameter_digest(restored.parameters),
                _parameter_digest(model.parameters),
            )
            np.testing.assert_array_equal(restored.predict(x), model.predict(x))

    def test_original_censored_targets_are_excluded_and_metadata_is_not_input(self):
        dataset = load_transitions(archive())
        x, y, groups = _data(dataset["records"])
        mask = np.isfinite(y)
        self.assertTrue((~mask).any())
        self.assertEqual(int((~mask).sum()), dataset["summary"]["censored"])
        self.assertTrue((x[:, 1] == 0).all())
        self.assertEqual(set(y[mask]), {0, 1})
        projection = copy.deepcopy(dataset["records"])
        for row in projection:
            for key in (
                "goal_sha256",
                "primitives",
                "readbacks",
                "measurements",
                "source",
                "record_sha256",
            ):
                row.pop(key)
            row["target"]["goal_observed"] = "ignored invocation-label metadata"
        px, py, pg = _data(projection)
        np.testing.assert_array_equal(px, x)
        np.testing.assert_array_equal(py, y)
        np.testing.assert_array_equal(pg, groups)
        with self.assertRaisesRegex(ValueError, "observed boolean targets"):
            CompletionAdvisor(0).loss_gradient(x, y)
        observed = _scores(np.array([0.0, 1.0]), np.array([0.2, 0.8]))
        censored = _scores(np.array([0.0, 1.0, np.nan]), np.array([0.2, 0.8, 0.99]))
        for key in ("brier", "log_loss", "confusion", "accuracy"):
            self.assertEqual(observed[key], censored[key])
        self.assertEqual((censored["observed"], censored["censored"]), (2, 1))

    def test_original_group_split_preserves_copies_and_admits_no_new_feature_holdout(
        self,
    ):
        dataset = load_transitions(archive())
        x, y, groups = _data(dataset["records"])
        plan = _plan(dataset, x, y, groups, {"unit_control": "no optimizer invoked"})
        by_hash = {r["record_sha256"]: r for r in dataset["records"]}
        self.assertEqual(len(by_hash), len(dataset["records"]))
        for fold in plan["folds"]:
            with self.subTest(group=fold["held_group"]):
                held, training = set(fold["held_records"]), set(fold["train_records"])
                self.assertFalse(held & training)
                self.assertEqual(held | training, set(by_hash))
                self.assertFalse(
                    {by_hash[h]["task_id"] for h in held}
                    & {by_hash[h]["task_id"] for h in training}
                )
                expected = {
                    r["record_sha256"]
                    for r, g in zip(dataset["records"], groups)
                    if g == fold["held_group"]
                }
                self.assertEqual(held, expected)
                self.assertEqual(
                    fold["held_rows_with_exact_feature_in_training"], len(held)
                )
                labels = y[groups == fold["held_group"]]
                if not np.isfinite(labels).any():
                    metrics = _scores(labels, np.full(len(labels), 0.5))
                    self.assertEqual(
                        (
                            metrics["observed"],
                            metrics["brier"],
                            metrics["log_loss"],
                            metrics["confusion"],
                        ),
                        (0, None, None, None),
                    )
        self.assertEqual(len(plan["feature_connected_components"]), 1)
        self.assertFalse(plan["independent_task_and_feature_holdout_available"])
        self.assertTrue(
            any(r["true"] and r["false"] for r in plan["visible_pattern_targets"])
        )

    def test_probe_rejects_changed_original_and_existing_output_before_any_fit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "archive"
            inputs.mkdir()
            for name in PINS:
                shutil.copyfile(archive() / name, inputs / name)
            output = root / "probe"
            with (inputs / "training-trajectories.jsonl.gz").open("ab") as stream:
                stream.write(b"changed original")
            with patch.object(
                CompletionAdvisor, "fit", side_effect=AssertionError("unqualified fit")
            ):
                with self.assertRaisesRegex(ValueError, "archive pin differs"):
                    run_probe(inputs, output)
            self.assertFalse(output.exists())
            output.mkdir()
            (output / "sentinel").write_bytes(b"original existing content")
            with patch.object(
                CompletionAdvisor, "fit", side_effect=AssertionError("unexpected fit")
            ):
                with self.assertRaises(FileExistsError):
                    run_probe(archive(), output)
            self.assertEqual(list(output.iterdir()), [output / "sentinel"])
            self.assertEqual(
                (output / "sentinel").read_bytes(), b"original existing content"
            )


if __name__ == "__main__":
    unittest.main()
