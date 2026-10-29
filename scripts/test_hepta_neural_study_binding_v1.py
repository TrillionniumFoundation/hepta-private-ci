#!/usr/bin/env python3
"""Finite provenance refusal controls, not model or product qualification."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import hepta_neural_study_v1 as study


class TrainingSourceBindings(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-training-source-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = (
            Path(__file__).resolve().parents[1]
            / "codex-rs/hepta-learning-artifacts/profiles/smollm2-public-initial-v2.plan.json"
        )
        self.raw = source.read_bytes()
        self.plan = json.loads(self.raw)
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_bytes(self.raw)
        self.ledger = self.root / "ledger"
        self.ledger.write_bytes(b"control fixture only; no authenticated ledger claim")
        offered = [row for row in self.plan["tasks"] if row["partition"] == "training"]
        self.value = dict(
            schema="hepta-neural-actual-training-data-v1",
            model_plan=study.pin(self.plan_path),
            offered_training_rows=offered,
            consumed_training_rows=copy.deepcopy(offered[:10]),
            consumed_step_indices=list(range(10)),
            source_dataset_digest="a" * 64,
            dataset_receipt={
                "snapshot": {
                    "dataset_digest": "a" * 64,
                    "source_record_digests": [f"{index:064x}" for index in range(20)],
                    "pending_outcomes": 0,
                    "censored_outcomes": 0,
                }
            },
            ledger=study.pin(self.ledger),
        )

    def check(self):
        return study.checked_training_data(self.value, self.plan, self.raw)

    def test_exact_original_supply_and_consumed_subset(self):
        rows = self.check()
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(row["expected_output"] == "yes" for row in rows), 5)
        self.assertEqual(sum("uppercase" in row["prompt"] for row in rows), 5)

    def test_reordered_actual_consumption_is_refused(self):
        self.value["consumed_training_rows"].reverse()
        with self.assertRaisesRegex(ValueError, "translation"):
            self.check()

    def test_unused_offered_row_cannot_be_claimed_as_consumed(self):
        self.value["consumed_training_rows"][-1] = self.value["offered_training_rows"][
            11
        ]
        with self.assertRaisesRegex(ValueError, "translation"):
            self.check()

    def test_changed_target_bytes_are_refused(self):
        self.value["consumed_training_rows"][0]["expected_output"] = "no"
        with self.assertRaisesRegex(ValueError, "translation"):
            self.check()

    def test_extra_counterfactual_records_are_refused(self):
        self.value["dataset_receipt"]["snapshot"]["source_record_digests"].append(
            "f" * 64
        )
        with self.assertRaisesRegex(ValueError, "no additional outcomes"):
            self.check()

    def test_wrong_dataset_digest_is_refused(self):
        self.value["source_dataset_digest"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "one authenticated target"):
            self.check()

    def test_changed_durable_ledger_bytes_are_refused(self):
        self.ledger.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "ledger bytes"):
            self.check()

    def test_plan_byte_change_is_refused_even_when_json_value_matches(self):
        self.plan_path.write_bytes(self.raw + b"\n")
        self.value["model_plan"] = study.pin(self.plan_path)
        with self.assertRaisesRegex(ValueError, "translation"):
            self.check()


if __name__ == "__main__":
    unittest.main()
