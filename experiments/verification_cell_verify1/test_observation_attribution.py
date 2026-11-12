"""Counterexamples separating later free ACKs from added paid readback signals."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import mock_open, patch

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
    def test_row_generator_stops_before_unbounded_materialization(self):
        consumed = 0

        def rows():
            nonlocal consumed
            while True:
                consumed += 1
                if consumed > 100001:
                    raise AssertionError("attribution consumed beyond its row bound")
                yield row("a")

        with self.assertRaisesRegex(ValueError, "bounded nonempty"):
            attribute_rows(rows())
        self.assertEqual(consumed, 100001)

    def test_post_audit_read_is_bounded_before_hash_or_allocation(self):
        class OversizedRead:
            def __len__(self):
                return 16_000_001

        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "trajectories.jsonl").write_bytes(b"small original")
            opener = mock_open()
            opener.return_value.read.return_value = OversizedRead()
            with (
                patch(
                    "experiments.verification_cell_verify1.observation_audit.audit",
                    return_value={},
                ),
                patch.object(Path, "open", opener),
                patch(
                    "experiments.verification_cell_verify1.observation_attribution.hashlib.sha256",
                    side_effect=AssertionError("oversized bytes reached hashing"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "byte bound after audit"):
                    attribute_run(path)
            opener.return_value.read.assert_called_once_with(16_000_001)

    def test_post_audit_symlink_is_not_read(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            target = path / "other"
            target.write_bytes(b"unselected content")
            try:
                (path / "trajectories.jsonl").symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("creating symlinks is unavailable on this platform")
            with (
                patch(
                    "experiments.verification_cell_verify1.observation_audit.audit",
                    return_value={},
                ),
                patch.object(
                    Path, "open", side_effect=AssertionError("symlink was opened")
                ),
            ):
                with self.assertRaisesRegex(ValueError, "indirect after audit"):
                    attribute_run(path)

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
