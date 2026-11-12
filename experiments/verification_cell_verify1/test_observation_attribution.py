"""Counterexamples separating later free ACKs from added paid readback signals."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from .observation_attribution import attribute_rows, attribute_run


def row(
    identity,
    *,
    acks=(True, True, True),
    presence=(True, True),
    error=False,
    source="source",
    phase="train",
):
    return dict(
        trajectory_id=identity,
        phase=phase,
        source_group=source,
        acks=acks,
        presence=presence,
        error=error,
    )


class ObservationAttributionTests(unittest.TestCase):
    def test_refuse_saved_records_changed_after_audit(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "trajectories.jsonl").write_text("changed\n")
            receipt = {"inputs": {"trajectories.jsonl": {"sha256": "0" * 64}}}
            with patch(
                "experiments.verification_cell_verify1.observation_audit.audit",
                return_value=receipt,
            ):
                with self.assertRaisesRegex(ValueError, "changed after"):
                    attribute_run(path)

    def test_later_free_ack_can_explain_all_apparent_paid_information(self):
        result = attribute_rows(
            [row("a", acks=(True, False, True), error=True), row("b")]
        )["cohorts"]["train"]["task_weighted"]
        self.assertEqual(result["empirical_resolution"]["initial_ack"]["value"], 0)
        self.assertEqual(result["empirical_resolution"]["late_acks"]["value"], 0.25)
        self.assertEqual(
            result["incremental_paid_resolution_given_late_acks"]["value"], 0
        )
        self.assertFalse(result["paid_increment_observed_in_supplied_rows"])

    def test_paid_presence_adds_information_conditionally_on_same_acks(self):
        result = attribute_rows(
            [row("a", presence=(True, False), error=True), row("b")]
        )
        metrics = result["cohorts"]["train"]["task_weighted"]
        self.assertEqual(metrics["empirical_resolution"]["late_acks"]["value"], 0)
        self.assertEqual(
            metrics["incremental_paid_resolution_given_late_acks"],
            {"value": 0.25, "numerator": 1, "denominator": 4},
        )
        self.assertFalse(result["population_information_established"])
        self.assertFalse(result["causal_paid_readback_value_established"])

    def test_source_weighting_differs_from_pooled_task_resolution(self):
        rows = [row(str(i), source="large") for i in range(6)]
        rows += [
            row("small-clean", source="small"),
            row("small-error", source="small", presence=(True, False), error=True),
        ]
        cohort = attribute_rows(rows)["cohorts"]["train"]
        self.assertEqual(
            cohort["equal_source_mean_incremental_resolution"]["value"], 0.125
        )
        self.assertEqual(
            cohort["task_weighted"]["incremental_paid_resolution_given_late_acks"][
                "value"
            ],
            7 / 64,
        )

    def test_refuse_unknown_duplicate_alias_and_cross_phase_sources(self):
        invalid = [
            [row("a", error=None)],
            [row("a", error=1)],
            [row("a", acks=(True, 1, True))],
            [row("a"), row("a")],
            [row("a"), row("b", phase="confirm")],
        ]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                attribute_rows(rows)
