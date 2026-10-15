"""Fail-closed TEST visibility, SOURCE identity and five-arm workflow tests.

All images/labels here are synthetic mechanism fixtures, not natural task data.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from e3_source_target_partition import (
    TargetPartitionError, partition_source_labels,
)
from e3_scienceqa_contract import SIZES, sha, canonical, read_jsonl
from e3_scienceqa_stage import prepare


def small_rows():
    return [
        ("train-1", "g1", "train", 0),
        ("validation-1", "g2", "validation", 1),
        ("test-1", "g3", "test", 2),
    ]


def complete_synthetic_membership():
    rows = {}
    for split, count in SIZES.items():
        batch = []
        for i in range(count):
            fields = {
                "question": f"Distinct research question {split} {i}?",
                "hint": "",
                "choices": ["A", "B", "C", "D"],
            }
            source = f"synthetic-not-original-image/{split}/{i}".encode()
            group = sha(f"independent-group/{split}/{i}".encode())
            token = sha(canonical(["source-membership", split, i]))
            batch.append((i, fields, source, group, token))
        rows[split] = batch
    return rows


class NoTargetVisibility(unittest.TestCase):
    def test_model_mode_does_not_read_test_answer_or_digest(self):
        seen = []
        def answer(split, index):
            seen.append((split, index))
            if split == "test":
                self.fail("TEST callback may not execute in predictor mode")
            return index % 4
        fit, held = partition_source_labels(small_rows(), answer, include_test_labels=False)
        self.assertEqual(len(fit), 2)
        self.assertEqual(held, [])
        self.assertEqual(seen, [("train", 0), ("validation", 1)])

    def test_evaluator_mode_includes_original_heldout(self):
        seen = []
        def answer(split, index):
            seen.append(split)
            return index % 4
        fit, held = partition_source_labels(small_rows(), answer, include_test_labels=True)
        self.assertEqual((len(fit), len(held)), (2, 1))
        self.assertEqual(seen, ["train", "validation", "test"])

    def test_bogus_visibility_type_rejected(self):
        with self.assertRaises(TargetPartitionError):
            partition_source_labels(small_rows(), lambda *_: 0, include_test_labels=1)

    def test_duplicate_or_unsupported_membership_rejected(self):
        with self.assertRaises(TargetPartitionError):
            partition_source_labels(small_rows() + [small_rows()[0]],
                                    lambda *_: 0, include_test_labels=False)
        with self.assertRaises(TargetPartitionError):
            partition_source_labels([("id", "g", "future4", 0)],
                                    lambda *_: 0, include_test_labels=False)

    def test_bool_and_out_of_range_answer_rejected(self):
        for illegal in (True, -1, 4, "1"):
            with self.subTest(illegal=illegal):
                with self.assertRaises(TargetPartitionError):
                    partition_source_labels(small_rows(), lambda *_: illegal,
                                            include_test_labels=False)

    def test_real_stage_predictor_and_label_owner_have_same_source(self):
        selected = complete_synthetic_membership()
        test_reads = []
        def label(split, index):
            if split == "test":
                test_reads.append(index)
            return index % 4
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_out = root / "predictor"
            eval_out = root / "evaluator"
            source_sha, fit_sha, held_sha = prepare(
                selected, label, source_out, include_test_labels=False)
            self.assertIsNone(held_sha)
            self.assertEqual(test_reads, [])
            self.assertFalse((source_out / "private_labels").exists())
            source_seals = json.loads((source_out / "source-seals.json").read_text())
            self.assertIsNone(source_seals["private_test_labels_sha256"])
            self.assertEqual(source_seals["source_sha256"], source_sha)
            self.assertEqual(source_seals["fit_labels_sha256"], fit_sha)
            prediction_source = read_jsonl(source_out / "inputs" / "sources.jsonl", source_sha)
            fit_labels = read_jsonl(source_out / "inputs" / "fit_labels.jsonl", fit_sha)
            self.assertEqual((len(prediction_source), len(fit_labels)), (192, 128))
            self.assertTrue(all("label" not in row and "answer" not in row
                                for row in prediction_source))
            other_source, other_fit, other_held = prepare(
                selected, label, eval_out, include_test_labels=True)
            self.assertEqual((source_sha, fit_sha), (other_source, other_fit))
            self.assertEqual(len(test_reads), 64)
            held = read_jsonl(eval_out / "private_labels" / "test_labels.jsonl", other_held)
            self.assertEqual(len(held), 64)

    def test_workflow_scopes_test_digest_to_independent_reviewer_only(self):
        path = Path(__file__).resolve().parents[2] / ".github/workflows/hepta-e3-five-arm-original-physical.yml"
        value = path.read_text(encoding="utf-8")
        header, jobs = value.split("\njobs:\n", 1)
        self.assertNotIn("HELD_SHA:", header)
        physical_ocr = jobs.split("  physical-ocr-granite:\n", 1)[1].split(
            "  physical-native-gemma2:\n", 1)[0]
        physical_native = jobs.split("  physical-native-gemma2:\n", 1)[1].split(
            "  independent-five-arm-review:\n", 1)[0]
        independent = jobs.split("  independent-five-arm-review:\n", 1)[1]
        for physical in (physical_ocr, physical_native):
            self.assertIn("e3_scienceqa_stage.py --output", physical)
            self.assertIn("--predictor-source-only", physical)
            self.assertIn("private_test_labels_sha256", physical)
            self.assertIn(" is None", physical)
            self.assertIn("test_labels.jsonl", physical)
            self.assertIn("not", physical)
            self.assertNotIn("HELD_SHA", physical)
        self.assertIn("HELD_SHA: b15cb81cbce3ff500ec58bb7da59c92801170bbce3b7995d689342505161f6d3",
                      independent)
        self.assertIn("e3_scienceqa_stage.py", independent)
        self.assertNotIn("--predictor-source-only", independent)
        self.assertIn("private_labels/test_labels.jsonl", independent)


if __name__ == "__main__":
    unittest.main()
