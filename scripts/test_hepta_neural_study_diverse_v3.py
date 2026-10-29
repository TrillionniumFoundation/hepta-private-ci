"""Actual entrypoint and finite dataset guards; no model or owner runs."""

import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hepta_neural_study_diverse_v3 as target


class DiverseStudyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = target.work.training_data()
        self.plan = dict(training_steps=10, fixture="material-plan-contract-only")
        self.raw = target.canonical(self.plan)
        (self.root / "plan.json").write_bytes(self.raw)
        (self.root / "ledger").write_bytes(
            b"finite fixture; no authenticated production ledger\n"
        )
        self.value = dict(
            schema="hepta-neural-actual-training-data-diverse-v3",
            model_plan=target.pin(self.root / "plan.json"),
            offered_training_rows=self.data["training_rows"],
            consumed_training_rows=self.data["training_rows"],
            consumed_step_indices=list(range(60)),
            source_dataset_digest="ab" * 32,
            dataset_receipt=dict(
                snapshot=dict(
                    dataset_digest="ab" * 32,
                    source_record_digests=[
                        format(index, "064x") for index in range(120)
                    ],
                    pending_outcomes=0,
                    censored_outcomes=0,
                )
            ),
            ledger=target.pin(self.root / "ledger"),
            row_encoding="finite fixture",
            record_semantics="no model prediction or qualification",
            frozen_unix_micros=1,
        )

    def verify(self, value=None):
        return target.checked_training_data(
            self.value if value is None else value, self.plan, self.raw, self.data
        )

    def test_sixty_explicit_rows_are_separate_from_the_unchanged_material_plan(self):
        self.assertEqual(self.verify(), self.data["training_rows"])
        self.assertEqual(self.plan["training_steps"], 10)
        self.assertNotIn("torch", sys.modules)

    def test_legacy_namespace_twenty_records_and_partial_rows_refuse(self):
        for field, value in (
            ("schema", "hepta-neural-actual-training-data-v1"),
            ("offered_training_rows", self.data["training_rows"][:12]),
            ("consumed_training_rows", self.data["training_rows"][:10]),
            ("consumed_step_indices", list(range(10))),
        ):
            changed = copy.deepcopy(self.value)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(changed)
        changed = copy.deepcopy(self.value)
        changed["dataset_receipt"]["snapshot"]["source_record_digests"] = [
            "aa" * 32
        ] * 20
        with self.assertRaises(ValueError):
            self.verify(changed)

    def test_ledger_plan_source_and_pending_outcomes_remain_bound(self):
        for field in ("dataset_digest", "pending_outcomes", "censored_outcomes"):
            changed = copy.deepcopy(self.value)
            changed["dataset_receipt"]["snapshot"][field] = "wrong"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(changed)
        (self.root / "ledger").write_bytes(b"changed after admission")
        with self.assertRaises(ValueError):
            self.verify()

    def test_closed_data_indices_and_frozen_time_cannot_be_relabelled(self):
        for field, value in (
            ("consumed_step_indices", [False, *range(1, 60)]),
            ("frozen_unix_micros", True),
            ("frozen_unix_micros", 2**63),
        ):
            changed = copy.deepcopy(self.value)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(changed)
        changed = copy.deepcopy(self.value)
        changed["arbitrary_training_recipe"] = "not-admitted"
        with self.assertRaises(ValueError):
            self.verify(changed)

    def test_unpublished_training_pin_fails_before_any_git_or_owner_call(self):
        with (
            patch.object(target, "TRAINING_COMMIT", None),
            patch.object(target, "TRAINING_TREE", None),
            patch.object(target.subprocess, "check_output") as command,
        ):
            with self.assertRaisesRegex(
                ValueError, "published exact diverse training source"
            ):
                target.checkout_training_tree(self.root)
            command.assert_not_called()

    def test_commit_and_tree_are_both_exact_before_source_checkout_verification(self):
        with (
            patch.object(target, "TRAINING_COMMIT", "a" * 40),
            patch.object(target, "TRAINING_TREE", "b" * 40),
            patch.object(
                target.subprocess,
                "check_output",
                return_value="a" * 40 + "\n" + "b" * 40 + "\n",
            ),
            patch.object(target.original, "checkout") as checkout,
        ):
            self.assertEqual(target.checkout_training_tree(self.root), "a" * 40)
            checkout.assert_called_once_with(self.root, "a" * 40)
        with (
            patch.object(target, "TRAINING_COMMIT", "a" * 40),
            patch.object(target, "TRAINING_TREE", "b" * 40),
            patch.object(
                target.subprocess,
                "check_output",
                return_value="c" * 40 + "\n" + "b" * 40 + "\n",
            ),
        ):
            with self.assertRaisesRegex(
                ValueError, "exact diverse training commit and tree"
            ):
                target.checkout_training_tree(self.root)

    def test_isolated_actual_entrypoint_loads_without_model_dependencies(self):
        result = subprocess.run(
            [sys.executable, "-I", "-B", target.__file__, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"--input-sha256", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
