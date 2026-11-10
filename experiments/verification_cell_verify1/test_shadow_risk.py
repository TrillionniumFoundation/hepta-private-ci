from dataclasses import asdict, replace
import hashlib
import json
import math
import unittest

from .shadow_risk import (
    Prediction,
    Snapshot,
    Target,
    TerminalLabel,
    evaluate_shadow,
    fit_risk_table,
)


SHA = "a" * 64
TARGET = Target("sqlite", "terminal_goal_error", 4, SHA)


def snapshot(identifier="t", group="eval", step=0, features=()):
    return Snapshot(identifier, group, SHA, TARGET, step, features)


def label(identifier="t", group="eval", disposition="accept", error=False):
    return TerminalLabel(
        identifier,
        group,
        SHA,
        TARGET,
        disposition,
        error,
        4,
        SHA if error is not None else None,
        None if error is not None else "readback_unavailable",
    )


class ShadowRiskTests(unittest.TestCase):
    def fit(self):
        observations = [
            snapshot(str(i), "train", step) for i in range(2) for step in (0, 2)
        ]
        labels = [label("0", "train", error=False), label("1", "train", error=True)]
        return fit_risk_table(observations, labels, TARGET, ("train",), ("eval",))

    def test_fit_freezes_train_only_frequency_and_unseen_refusal(self):
        model = self.fit()
        self.assertEqual(model.training_label_count, 2)
        self.assertEqual(model.predict(snapshot()).probability, 0.5)
        self.assertIsNone(model.predict(snapshot(features=(1,))).probability)
        self.assertEqual(model, self.fit())
        self.assertNotEqual(model.data_sha256, model.model_sha256)

    def test_monitor_tracks_multiple_frontiers_without_inventing_independence(self):
        model = self.fit()
        predictions = [model.predict(snapshot(step=step)) for step in (0, 2)]
        result = evaluate_shadow(predictions, [label(error=True)])
        self.assertEqual((result["trajectories"], result["prediction_count"]), (1, 2))
        self.assertEqual(result["by_step"]["0"]["brier"], 0.25)
        self.assertAlmostEqual(result["by_step"]["2"]["log_loss"], math.log(2))
        self.assertFalse(result["independent_sampling_established"])

    def test_dispositions_are_separate_from_truth_and_missing_labels(self):
        labels = [
            label("a", disposition="accept", error=True),
            label("m", disposition="accept", error=None),
            label("r", disposition="reject", error=False),
            label("i", disposition="interrupted", error=True),
            label("u", disposition="unknown", error=False),
        ]
        result = evaluate_shadow(
            [Prediction(snapshot(row.trajectory_id), 0.5, SHA) for row in labels],
            labels,
        )
        self.assertEqual(result["acceptance_coverage"], 0.4)
        self.assertEqual(result["accepted_error_missing_label_bounds"], [0.5, 1])
        self.assertEqual(
            result["all_trajectory_false_accept_missing_label_bounds"], [0.2, 0.4]
        )
        self.assertEqual(
            result["by_disposition"]["accept"]["label_acquisition_rate"], 0.5
        )
        self.assertEqual(result["by_step"]["0"]["scored"], 4)
        json.dumps(result, allow_nan=False)

    def test_zero_acceptance_is_undefined(self):
        result = evaluate_shadow([], [label(disposition="reject")])
        self.assertIsNone(result["accepted_error_missing_label_bounds"])
        self.assertEqual(result["acceptance_coverage"], 0)
        self.assertEqual(result["trajectories_with_predictions"], 0)

    def test_proper_log_loss_infinities_remain_explicit_and_json_safe(self):
        result = evaluate_shadow([Prediction(snapshot(), 0, SHA)], [label(error=True)])
        self.assertEqual(result["by_step"]["0"]["infinite_log_loss_count"], 1)
        self.assertIsNone(result["by_step"]["0"]["log_loss"])
        self.assertEqual(result["by_step"]["0"]["brier"], 1)
        json.dumps(result, allow_nan=False)

    def test_missing_and_unsupported_predictions_keep_denominators(self):
        result = evaluate_shadow(
            [Prediction(snapshot(), None, SHA)], [label(error=None)]
        )
        self.assertEqual(result["by_step"]["0"]["unsupported"], 1)
        self.assertEqual(result["by_step"]["0"]["missing_labels"], 1)
        self.assertIsNone(result["by_step"]["0"]["brier"])
        self.assertEqual(
            result["by_disposition"]["accept"]["missing_reasons"],
            {"readback_unavailable": 1},
        )

    def test_different_frozen_models_cannot_be_pooled(self):
        with self.assertRaises(ValueError):
            evaluate_shadow(
                [
                    Prediction(snapshot("a"), 0.5, SHA),
                    Prediction(snapshot("b"), 0.5, "b" * 64),
                ],
                [label("a"), label("b")],
            )

    def test_split_and_target_leakage_are_rejected(self):
        model = self.fit()
        for row in (
            snapshot(group="train"),
            snapshot(group="new"),
            replace(snapshot(), target=replace(TARGET, horizon_end=5)),
            replace(snapshot(), target=replace(TARGET, event="after_repair_error")),
        ):
            with self.subTest(row=row), self.assertRaises(ValueError):
                model.predict(row)
        with self.assertRaises(ValueError):
            fit_risk_table(
                [snapshot(group="train")],
                [label(group="train")],
                TARGET,
                ("train",),
                ("train",),
            )

    def test_duplicate_missing_and_mismatched_records_fail_closed(self):
        prediction = Prediction(snapshot(), 0.5, SHA)
        for predictions, labels in (
            ([prediction, prediction], [label()]),
            ([prediction], [label(), label()]),
            ([prediction], []),
            ([prediction], [replace(label(), subject_sha256="b" * 64)]),
            ([prediction], [replace(label(), source_group="other")]),
        ):
            with (
                self.subTest(predictions=predictions, labels=labels),
                self.assertRaises(ValueError),
            ):
                evaluate_shadow(predictions, labels)

    def test_known_labels_cannot_be_early_or_unbacked(self):
        for changes in (
            {"observed_step": 2},
            {"evidence_sha256": None},
            {"missing_reason": "unknown"},
            {"error": 0},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(label(), **changes)
        missing = replace(label(error=None), disposition="interrupted", observed_step=2)
        self.assertIsNone(missing.error)

    def test_invalid_numbers_and_retrospective_features_rejected(self):
        for value in (True, float("nan"), float("inf"), -0.1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Prediction(snapshot(), value, SHA)
        for features in ((True,), (float("nan"),), (float("inf"),)):
            with self.subTest(features=features), self.assertRaises(ValueError):
                snapshot(features=features)
        with self.assertRaises(ValueError):
            snapshot(step=4)

    def test_missing_training_labels_excluded_without_assuming_success(self):
        rows = [snapshot("a", "train"), snapshot("b", "train")]
        labels = [label("a", "train", error=True), label("b", "train", error=None)]
        model = fit_risk_table(rows, labels, TARGET, ("train",), ("eval",))
        self.assertEqual(
            (model.training_label_count, model.missing_training_labels), (1, 1)
        )
        self.assertAlmostEqual(model.predict(snapshot()).probability, 2 / 3)

    def test_old_identity_cannot_hide_changed_cells_counts_or_split(self):
        model = self.fit()
        altered = tuple(
            (step, features, 0, count) for step, features, _, count in model.cells
        )
        for change in (
            {"cells": altered},
            {"training_label_count": 3},
            {"missing_training_labels": 1},
            {"data_sha256": "b" * 64},
            {"evaluation_groups": ("other",)},
            {"target": replace(TARGET, horizon_end=5)},
        ):
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "frozen v2 digest"),
            ):
                replace(model, **change)

    def test_legacy_v1_artifact_requires_explicit_refreeze(self):
        model = self.fit()
        legacy = {
            "version": "verify-shadow-frequency-v1",
            "target": asdict(model.target),
            "training_groups": model.training_groups,
            "evaluation_groups": model.evaluation_groups,
            "cells": model.cells,
            "prior": [1, 1],
            "data_sha256": model.data_sha256,
        }
        old_digest = hashlib.sha256(
            json.dumps(
                legacy, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "frozen v2 digest"):
            replace(model, model_sha256=old_digest)
        prediction = model.predict(snapshot())
        self.assertEqual(
            (prediction.model_sha256, prediction.probability), (model.model_sha256, 0.5)
        )
        self.assertNotEqual(model.model_sha256, old_digest)

    def test_risk_model_requires_canonical_immutable_cells_and_groups(self):
        model = self.fit()
        mutations = [
            {"cells": list(model.cells)},
            {"cells": (list(model.cells[0]),)},
            {"cells": ((0, [], 1, 2),)},
            {"cells": model.cells[::-1]},
            {"cells": (model.cells[0], model.cells[0])},
            {"cells": ((0, (float("nan"),), 1, 2),)},
            {"cells": ((0, (1,), 1, 2),)},
            {"cells": ((True, (), 1, 2),)},
            {"cells": ((4, (), 1, 2),)},
            {"cells": ((0, (), True, 2),)},
            {"cells": ((0, (), 3, 2),)},
            {"cells": ((0, (), 0, 0),)},
            {"training_groups": ["train"]},
            {"training_groups": ("z", "a")},
            {"training_groups": ("train", "train")},
            {"evaluation_groups": ("train",)},
        ]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(model, **change)

    def test_pooled_frontiers_must_be_consistent_with_unique_label_denominators(self):
        model = self.fit()
        for change in (
            {"training_label_count": True},
            {"training_label_count": 0},
            {"missing_training_labels": -1},
            {"missing_training_labels": 100000},
        ):
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, "denominators"),
            ):
                replace(model, **change)
        with self.assertRaisesRegex(ValueError, "contradict label roster"):
            replace(model, training_label_count=5)
        with self.assertRaisesRegex(ValueError, "contradict shared terminal labels"):
            replace(model, cells=((0, (), 0, 2), (2, (), 2, 2)))

    def test_partial_frontiers_and_missing_labels_keep_their_distinct_counts(self):
        observations = [
            snapshot("a", "train-a", 0),
            snapshot("b", "train-a", 2),
            snapshot("c", "train-b", 2),
            snapshot("d", "train-b", 0),
        ]
        labels = [
            label("a", "train-a", error=True),
            label("b", "train-a", error=False),
            label("c", "train-b", error=True),
            label("d", "train-b", error=None),
        ]
        model = fit_risk_table(
            observations, labels, TARGET, ("train-b", "train-a"), ("eval",)
        )
        self.assertEqual(
            (model.training_label_count, model.missing_training_labels), (3, 1)
        )
        self.assertAlmostEqual(model.predict(snapshot()).probability, 2 / 3)
        self.assertEqual(model.predict(snapshot(step=2)).probability, 0.5)

    def test_predict_revalidates_restored_or_mutated_model_content(self):
        for field, value in (
            ("cells", ((0, (), 0, 2), (2, (), 0, 2))),
            ("missing_training_labels", 1),
            ("evaluation_groups", ("eval", "foreign")),
        ):
            with self.subTest(field=field):
                model = self.fit()
                object.__setattr__(model, field, value)
                with self.assertRaisesRegex(ValueError, "frozen v2 digest"):
                    model.predict(snapshot())


if __name__ == "__main__":
    unittest.main()
