"""Gold separation, two-source evidence and negative-control test fixtures."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from hepta_sngr_reader_eval import load_cases, ReaderBenchError, option_presentation
from hepta_sngr_two_source_eval import (
    CHOICES,
    FROZEN_PAIR_SHA256,
    TRUTH_TO_LABEL,
    expected_label,
    lexical_pair_audit,
    load_pairs,
    main,
    pair_request,
    run_pairs,
)

ROOT = Path(__file__).parent


class UnavailableReaderStub:
    """Test-only UNKNOWN stub. Never claim a genuine reader result."""

    def predict(self, state, questions):
        probs = {label: float(label == "UNKNOWN") for label in (*"ABCD", "UNKNOWN")}
        return {
            "answers": {
                "answer": {
                    "choice": "UNKNOWN",
                    "confidence": 1.0,
                    "probabilities": probs,
                }
            },
            "usage": {"input_tokens": 128},
        }


class TwoSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = load_cases(ROOT / "hepta_sngr_reader_cases.json")
        cls.paired = load_pairs(ROOT / "hepta_sngr_two_source_cases.json", cls.parent)

    def test_manifest_is_exact_8_case_two_source_truth_table(self):
        self.assertEqual(len(self.paired["tasks"]), 8)
        self.assertEqual(self.paired["manifest_sha256"], FROZEN_PAIR_SHA256)
        self.assertEqual(set(CHOICES), set("ABCD"))
        self.assertEqual(set(TRUTH_TO_LABEL.values()), set("ABCD"))
        parent = {t["id"]: t for t in self.parent["tasks"]}
        labels = {k: 0 for k in "ABCD"}
        for task in self.paired["tasks"]:
            labels[expected_label(task)] += 1
            a, b = (parent[i]["source"] for i in task["source_task_ids"])
            self.assertNotEqual(a["path"], b["path"])
            self.assertTrue(all(t is True or t is False for t in task["truths"]))
        self.assertEqual(labels, dict.fromkeys("ABCD", 2))

    def test_full_condition_contains_both_independent_real_quotes(self):
        parent = {t["id"]: t for t in self.parent["tasks"]}
        for pair in self.paired["tasks"]:
            src_a, src_b = (
                parent[tid]["source"]["quote"] for tid in pair["source_task_ids"]
            )
            state, questions = pair_request(self.parent, pair, "full", CHOICES)
            self.assertIn(src_a, state["untrusted_excerpt_1"])
            self.assertIn(src_b, state["untrusted_excerpt_2"])
            self.assertEqual(
                set(questions["answer"]["criteria"]), set("ABCD") | {"UNKNOWN"}
            )
            withheld, _ = pair_request(self.parent, pair, "withheld", CHOICES)
            self.assertIn(src_a, withheld["untrusted_excerpt_1"])
            self.assertNotIn(src_b, withheld["untrusted_excerpt_2"])
            none, _ = pair_request(self.parent, pair, "none", CHOICES)
            self.assertNotIn(src_a, none["untrusted_excerpt_1"])
            self.assertNotIn(src_b, none["untrusted_excerpt_2"])

    def test_gold_blind_transport_and_causal_pairing_under_rotations(self):
        for task in self.paired["tasks"]:
            modified = copy.deepcopy(task)
            modified["truths"] = [not val for val in task["truths"]]
            seen_positions = set()
            for variant in range(4):
                choices, shift = option_presentation(
                    {"id": task["id"], "choices": CHOICES}, 43, variant, presentations=4
                )
                predicted_gold = "ABCD"[
                    ("ABCD".index(expected_label(task)) + shift) % 4
                ]
                self.assertEqual(choices[predicted_gold], CHOICES[expected_label(task)])
                seen_positions.add(predicted_gold)
                for arm in ("none", "distractor", "withheld", "full", "injection"):
                    actual = pair_request(self.parent, task, arm, choices)
                    changed = pair_request(self.parent, modified, arm, choices)
                    self.assertEqual(actual, changed)
                    self.assertNotIn("truths", str(actual))
                    self.assertNotIn("gold", str(actual))
            self.assertEqual(seen_positions, set("ABCD"))

    def test_plain_lexical_control_does_not_solve_joint_truth(self):
        report = lexical_pair_audit(self.parent, self.paired, presentations=4)
        self.assertIn("not_model", report["evidence_class"])
        self.assertEqual(
            report["result"]["full"], {"matched": 0, "total": 32, "abstentions": 32}
        )
        self.assertEqual(report["result"]["withheld"]["matched"], 32)
        self.assertEqual(report["result"]["distractor"]["matched"], 32)

    def test_mock_reader_cannot_claim_efficacy_and_enforces_budget(self):
        report = run_pairs(
            self.parent,
            self.paired,
            UnavailableReaderStub(),
            "a" * 64,
            presentations=4,
            include_injection=True,
            max_calls=160,
            max_input_tokens=512,
        )
        self.assertEqual(report["model_calls"], 160)
        self.assertFalse(report["production_selection_authority"])
        self.assertIn("not_heldout", report["scope_limit"])
        self.assertEqual(
            report["summaries"]["none"]["evidence_condition_accuracy"], 1.0
        )
        self.assertEqual(
            report["summaries"]["withheld"]["evidence_condition_accuracy"], 1.0
        )
        self.assertEqual(
            report["summaries"]["full"]["evidence_condition_accuracy"], 0.0
        )
        with self.assertRaisesRegex(ReaderBenchError, "budget"):
            run_pairs(
                self.parent,
                self.paired,
                UnavailableReaderStub(),
                "a" * 64,
                presentations=4,
                include_injection=True,
                max_calls=159,
            )
        with self.assertRaisesRegex(ReaderBenchError, "saturation"):
            run_pairs(
                self.parent,
                self.paired,
                UnavailableReaderStub(),
                "a" * 64,
                max_input_tokens=128,
            )

    def test_unavailable_checkpoint_and_deterministic_lexical_cli(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            output = root / "paired.json"
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                self.assertEqual(main(["--output", str(output)]), 2)
            self.assertEqual(json.loads(console.getvalue())["status"], "unavailable")
            self.assertFalse(output.exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--lexical-control-only",
                            "--presentations",
                            "4",
                            "--output",
                            str(output),
                        ]
                    ),
                    0,
                )
            receipt = json.loads(output.read_text())
            self.assertEqual(receipt["presentations"], 4)
            self.assertEqual(
                receipt["source_verification"], "pinned_parent_manifest_only"
            )
            first = output.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--lexical-control-only",
                            "--presentations",
                            "4",
                            "--output",
                            str(output),
                        ]
                    ),
                    0,
                )
            self.assertEqual(output.read_bytes(), first)

    def test_bad_dataset_bytes_fail_before_any_model_call(self):
        with tempfile.TemporaryDirectory() as d:
            parent_path = ROOT / "hepta_sngr_reader_cases.json"
            content = json.loads(
                (ROOT / "hepta_sngr_two_source_cases.json").read_text()
            )
            content["tasks"][0]["truths"][0] = False
            path = Path(d) / "modified.json"
            path.write_text(json.dumps(content))
            with self.assertRaisesRegex(ReaderBenchError, "unreviewed"):
                load_pairs(path, self.parent)
            self.assertTrue(parent_path.is_file())


if __name__ == "__main__":
    unittest.main()
