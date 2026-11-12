"""Counterexamples for observation leakage, clustering and calibration drift."""

import unittest

from .observation_diagnostics import analyze_observations


def row(
    case,
    *,
    source=None,
    phase="confirm",
    view="ack",
    error=False,
    risk=0.0,
    features=(True,),
):
    return dict(
        case_id=case,
        source_group=source or case,
        phase=phase,
        view_kind=view,
        feature_key=list(features),
        terminal_error=error,
        risk_probability=risk,
        decision="skip",
        available_step=1,
        decision_step=1,
        model_sha256="a" * 64,
        input_schema_sha256="b" * 64,
    )


class ObservationDiagnosticsTests(unittest.TestCase):
    def test_row_generator_is_stopped_at_bound_plus_one(self):
        consumed = 0

        def rows():
            nonlocal consumed
            while True:
                consumed += 1
                if consumed > 100001:
                    raise AssertionError("diagnostics consumed beyond its row bound")
                yield row("a")

        with self.assertRaisesRegex(ValueError, "bounded nonempty"):
            analyze_observations(rows())
        self.assertEqual(consumed, 100001)

    def test_bin_generator_is_stopped_at_bound_plus_one(self):
        consumed = 0

        def bins():
            nonlocal consumed
            while True:
                consumed += 1
                if consumed > 22:
                    raise AssertionError("diagnostics consumed beyond its bin bound")
                yield 0.0

        with self.assertRaisesRegex(ValueError, "frozen bins"):
            analyze_observations([row("a")], bins=bins())
        self.assertEqual(consumed, 22)

    def test_ack_ambiguity_and_later_readback_are_separate(self):
        rows = []
        for case, error in (("a", False), ("b", True)):
            rows += [
                row(case, error=error),
                row(case, view="readback", error=error, features=(not error,)),
            ]
        result = analyze_observations(rows)["cohorts"]
        ack, readback = [
            result["confirm/" + view]["information"] for view in ("ack", "readback")
        ]
        self.assertEqual(
            (ack["empirical_cell_oracle_accuracy_known"], ack["mixed_label_cells"]),
            (0.5, 1),
        )
        self.assertEqual(readback["empirical_cell_oracle_accuracy_known"], 1.0)
        self.assertFalse(
            readback["population_information_or_generalization_established"]
        )

    def test_unequal_cluster_weights_are_reported_separately(self):
        rows = [row(str(i), source="large") for i in range(9)] + [
            row("small", error=True)
        ]
        cohort = analyze_observations(rows)["cohorts"]["confirm/ack"]
        self.assertEqual(cohort["task_weighted"]["brier"], 0.1)
        self.assertEqual(cohort["equal_source_mean_brier"], 0.5)

    def test_probability_information_can_exist_without_accuracy_improvement(self):
        rows = [row(str(i), error=(i == 0), features=(i >= 3,)) for i in range(6)]
        info = analyze_observations(rows)["cohorts"]["confirm/ack"]["information"]
        self.assertEqual(info["empirical_cell_oracle_accuracy_known"], 5 / 6)
        self.assertEqual(info["empirical_best_constant_accuracy_known"], 5 / 6)
        self.assertAlmostEqual(info["empirical_probability_resolution_known"], 1 / 36)
        unknown = analyze_observations([row("unknown", error=None)])
        info = unknown["cohorts"]["confirm/ack"]["information"]
        self.assertIsNone(info["empirical_probability_resolution_known"])

    def test_unknown_labels_and_predictions_stay_in_denominator(self):
        result = analyze_observations(
            [
                row("known", error=True),
                row("unlabeled", error=None),
                row("unscored", risk=None),
            ]
        )
        metrics = result["cohorts"]["confirm/ack"]["task_weighted"]
        self.assertEqual(
            (
                metrics["rows"],
                metrics["unknown_labels"],
                metrics["unknown_predictions"],
                metrics["scored"],
            ),
            (3, 1, 1, 1),
        )
        self.assertEqual(metrics["missed_errors_per_row_bounds"], [1 / 3, 2 / 3])

    def test_refuse_identity_features_and_late_observations(self):
        changes = (
            {"feature_key": ["task-1"]},
            {"feature_key": [1]},
            {"available_step": 2},
            {"risk_probability": True},
            {"risk_probability": float("nan")},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                analyze_observations([{**row("a"), **change}])

    def test_refuse_source_leakage_duplicate_and_changed_case_truth(self):
        other = [
            row("b", source="same", phase="cal"),
            row("a", source="same"),
            row("a", source="same", view="readback", error=True),
        ]
        for candidate in other:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                analyze_observations([row("a", source="same"), candidate])

    def test_model_and_schema_updates_invalidate_calibration_reuse(self):
        baseline = row("cal", phase="cal")
        updated = {
            **row("shift", phase="shift"),
            "model_sha256": "c" * 64,
            "input_schema_sha256": "d" * 64,
        }
        drift = analyze_observations([baseline, updated])["drift"]["shift/ack"]
        self.assertTrue(drift["recalibration_required"])
        self.assertEqual(
            drift["reasons"], ["model_sha256_changed", "input_schema_sha256_changed"]
        )
        self.assertIsNone(drift["brier_change"])

    def test_fixed_model_drift_is_descriptive_and_bins_are_fixed(self):
        rows = [
            row("cal", phase="cal"),
            row("shift", phase="shift", error=True, risk=0.25),
        ]
        result = analyze_observations(rows)
        self.assertEqual(result["drift"]["shift/ack"]["brier_change"], 0.5625)
        self.assertIsNone(result["drift"]["shift/ack"]["recalibration_required"])
        self.assertEqual(
            result["drift"]["shift/ack"]["statistical_drift_decision"], "NOT_PERFORMED"
        )
        bins = result["cohorts"]["shift/ack"]["task_weighted"]["reliability"]
        self.assertEqual([item["predictions"] for item in bins], [0, 1, 0, 0])
        for invalid in ((0.0, 0.5, 0.5, 1.0), (0.1, 1.0), (False, 1.0)):
            with self.assertRaises(ValueError):
                analyze_observations(rows, bins=invalid)

    def test_missing_calibration_blocks_reuse(self):
        rows = [row("cal", phase="cal", error=None), row("confirm")]
        drift = analyze_observations(rows)["drift"]["confirm/ack"]
        self.assertTrue(drift["calibration_reuse_blocked"])
        self.assertEqual(drift["reasons"], ["calibration_observations_incomplete"])
        self.assertIsNone(drift["brier_change"])

    def test_partial_labels_and_unsupported_current_block_drift_comparison(self):
        calibration = [
            row("cal-known", phase="cal"),
            row("cal-missing", phase="cal", error=None),
        ]
        current = row("current", error=True)
        drift = analyze_observations(calibration + [current])["drift"]["confirm/ack"]
        self.assertTrue(drift["calibration_reuse_blocked"])
        self.assertIsNone(drift["brier_change"])
        for change in ({"risk_probability": None}, {"terminal_error": None}):
            report = analyze_observations(
                [row("cal", phase="cal"), {**current, **change}]
            )
            drift = report["drift"]["confirm/ack"]
            self.assertEqual(drift["reasons"], ["current_observations_incomplete"])
            self.assertTrue(drift["recalibration_required"])
            self.assertIsNone(drift["ece_change"])
