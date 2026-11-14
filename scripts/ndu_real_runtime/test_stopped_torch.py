"""Selector fixtures and separate real-Torch frozen-checkpoint integration tests."""

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from .controllers import ControlPlan, PublicState
from .objective import canonical_sha
from .stopped_torch import FrozenMacroPredictor, select_stopped_macros, source_identity
from .test_recursive_contract import numerical_records
from .trajectory import V2_FIELDS, V2_SCHEMA

WEIGHTS = "e" * 64


def linked(rows):
    for index, row in enumerate(rows):
        row["previous_record_sha256"] = (
            rows[index - 1]["record_sha256"] if index else None
        )
        row["record_sha256"] = canonical_sha(
            {key: value for key, value in row.items() if key != "record_sha256"}
        )
    return rows


def records(*, legacy=False):
    rows = numerical_records(ControlPlan())
    for index, row in enumerate(rows):
        row["record_id"] = row["origin_run_id"] + f"/transition/{index:02d}"
        row["behavior_weights_sha256"] = WEIGHTS
    linked(rows)
    if legacy:
        rows = [
            {key: value for key, value in row.items() if key not in V2_FIELDS}
            for row in rows
        ]
        for row in rows:
            row["schema"] = "ndu.real.training-transition.v1"
    return rows


class StoppedSelectorTests(unittest.TestCase):
    def test_exact_adjacent_stop_and_stop_only_keep_original_source(self):
        rows = records()
        original = copy.deepcopy(rows)
        macros, report = select_stopped_macros(
            list(reversed(rows)), expected_behavior_weights_sha256=WEIGHTS
        )
        self.assertEqual([m.start_row["action"] for m in macros], ["READ_ROI", "STOP"])
        self.assertEqual([m.duration_seconds for m in macros], [0.2, 0.1])
        self.assertEqual([m.terminal_utility for m in macros], [0.8, 0.8])
        self.assertEqual(rows, original)
        self.assertEqual(macros[0].records_sha256, canonical_sha(rows))
        self.assertEqual(report["excluded_episodes"], {})
        self.assertTrue(report["macro_observations_overlap_and_costs_are_not_additive"])

    def test_legacy_has_explicit_adjacency_without_schema_upgrade(self):
        rows = records(legacy=True)
        macros, report = select_stopped_macros(
            rows, expected_behavior_weights_sha256=WEIGHTS
        )
        self.assertEqual(len(macros), 2)
        self.assertNotEqual(macros[0].start_row["schema"], V2_SCHEMA)
        self.assertNotIn("episode_step", macros[0].start_row)
        self.assertFalse(report["legacy_schema_rewritten"])
        with self.assertRaisesRegex(ValueError, "ordinals"):
            select_stopped_macros(rows[1:], expected_behavior_weights_sha256=WEIGHTS)

    def test_wrong_behavior_or_evaluation_split_cannot_relabel_outcomes(self):
        rows = records(legacy=True)
        with self.assertRaisesRegex(ValueError, "different behavior"):
            select_stopped_macros(rows, expected_behavior_weights_sha256="f" * 64)
        rows[0]["split"] = "confirmation"
        with self.assertRaisesRegex(ValueError, "train"):
            select_stopped_macros(rows, expected_behavior_weights_sha256=WEIGHTS)

    def test_successor_source_and_utility_mismatches_fail(self):
        for mutate in (
            lambda row: row.update(source_group="other-source"),
            lambda row: row.update(before_score=0.3),
            lambda row: row.update(candidate_features=[[0.0] * 126]),
        ):
            rows = records(legacy=True)
            mutate(rows[1])
            with self.assertRaises(ValueError):
                select_stopped_macros(rows, expected_behavior_weights_sha256=WEIGHTS)
        rows = records()
        rows[-1]["after_score"] = 0.9
        with self.assertRaisesRegex(ValueError, "STOP"):
            select_stopped_macros(
                linked(rows), expected_behavior_weights_sha256=WEIGHTS
            )

    def test_failed_and_budget_terminals_retained_as_exclusions(self):
        for status in ("failed", "budget"):
            rows = records()
            if status == "failed":
                rows[-1].update(execution_status="failed", after_score=None)
            else:
                rows[-1].update(action="WRITE_TEXT", terminal_reason="budget_stop")
            macros, report = select_stopped_macros(
                linked(rows), expected_behavior_weights_sha256=WEIGHTS
            )
            self.assertEqual(macros, ())
            self.assertEqual(sum(report["excluded_episodes"].values()), 1)
            self.assertEqual(report["input_records"], 3)
            self.assertAlmostEqual(report["input_recorded_duration_seconds"], 0.3)

    def test_duplicate_and_missing_original_identities_fail(self):
        rows = records()
        with self.assertRaisesRegex(ValueError, "Repeated"):
            select_stopped_macros(
                rows + [rows[-1]], expected_behavior_weights_sha256=WEIGHTS
            )
        rows = records(legacy=True)
        rows[1]["record_id"] = "invented-adjacency"
        with self.assertRaisesRegex(ValueError, "ordinal"):
            select_stopped_macros(rows, expected_behavior_weights_sha256=WEIGHTS)


class FrozenPredictorTorchTests(unittest.TestCase):
    """Requires actual Torch; select this class only in a Torch-enabled runtime."""

    def setUp(self):
        import torch
        from .neural import ReceiptPortfolioModel, STATE_WIDTH

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "weights.pt"
        torch.manual_seed(5)
        torch.save(ReceiptPortfolioModel("ordinary").state_dict(), self.path)
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.predictor = FrozenMacroPredictor(
            self.path,
            expected_weights_sha256=self.digest,
            expected_source_sha256=source_identity(),
            core="ordinary",
        )
        self.state = PublicState((0.0,) * STATE_WIDTH, 60, 0, ("WRITE_TEXT", "STOP"))

    def test_loaded_behavior_center_and_frozen_parameters(self):
        stop = self.predictor.center(self.state, "STOP")
        continuation = self.predictor.center(self.state, "WRITE_TEXT")
        self.assertEqual(stop.next_features, self.state.features)
        self.assertGreater(stop.duration_seconds, 0)
        self.assertGreater(continuation.duration_seconds, 0)
        self.assertEqual(self.predictor.binding["weights_sha256"], self.digest)
        self.assertTrue(
            all(not p.requires_grad for p in self.predictor.model.parameters())
        )

    def test_content_mutation_cannot_reuse_old_behavior_identity(self):
        import torch

        with torch.no_grad():
            next(self.predictor.model.content_parameters()).add_(0.1)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.predictor.center(self.state, "STOP")

    def test_different_checkpoint_or_source_pin_is_refused(self):
        for weights, source in (("f" * 64, source_identity()), (self.digest, "f" * 64)):
            with self.assertRaises(ValueError):
                FrozenMacroPredictor(
                    self.path,
                    expected_weights_sha256=weights,
                    expected_source_sha256=source,
                    core="ordinary",
                )


if __name__ == "__main__":
    unittest.main()
