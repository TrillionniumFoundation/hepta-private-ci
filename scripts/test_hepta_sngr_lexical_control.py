"""Reference-only regression for the gold-blind lexical shortcut negative control."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from hepta_sngr_lexical_control import SCHEMA, audit, lexical_decision, main
from hepta_sngr_reader_eval import (
    ARM_NAMES,
    construct_request,
    load_cases,
    option_presentation,
)

CASES = Path(__file__).with_name("hepta_sngr_reader_cases.json")


class LexicalNegativeControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = load_cases(CASES)

    def test_post_hoc_shortcut_genuine_document_fixture(self):
        result = audit(self.corpus)
        self.assertEqual(result["schema"], SCHEMA)
        self.assertTrue(result["no_model_checkpoint_or_training_used"])
        self.assertIn("post_hoc", result["evidence_class"])
        self.assertIn("not_a_preregistered", result["post_hoc_rule_warning"])
        self.assertEqual(
            result["summaries"]["full"],
            {
                "cases": 16,
                "gold_matches": 14,
                "evidence_condition_matches": 14,
                "abstentions": 2,
            },
        )
        for arm in ("none", "distractor", "withheld"):
            self.assertEqual(result["summaries"][arm]["evidence_condition_matches"], 16)
            self.assertEqual(result["summaries"][arm]["abstentions"], 16)
        self.assertEqual(result["summaries"]["injection"]["gold_matches"], 14)
        self.assertFalse(result["production_selection_authority"])

    def test_four_rotations_preserve_scores_by_source_not_answer_position(self):
        result = audit(self.corpus, seed=71, presentations=4)
        self.assertEqual(result["summaries"]["full"]["gold_matches"], 56)
        self.assertEqual(result["summaries"]["full"]["cases"], 64)
        self.assertEqual(result["summaries"]["none"]["abstentions"], 64)
        for task in self.corpus["tasks"]:
            rows = [r for r in result["rows"] if r["task_id"] == task["id"]]
            self.assertEqual(len(rows), 20)
            self.assertEqual(len({r["presentation"] for r in rows}), 4)

    def test_decisions_do_not_consult_gold_even_when_it_is_mutated(self):
        for task in self.corpus["tasks"]:
            mutated = copy.deepcopy(task)
            mutated["gold"] = next(label for label in "ABCD" if label != task["gold"])
            for variant in range(4):
                choices, _ = option_presentation(task, 17, variant, presentations=4)
                other, _ = option_presentation(mutated, 17, variant, presentations=4)
                self.assertEqual(choices, other)
                for arm in ARM_NAMES + ("injection",):
                    state, questions = construct_request(
                        self.corpus, task, arm, choices_override=choices
                    )
                    mutated_state, mutated_questions = construct_request(
                        self.corpus, mutated, arm, choices_override=other
                    )
                    self.assertEqual(
                        (state, questions), (mutated_state, mutated_questions)
                    )
                    self.assertEqual(
                        lexical_decision(state, questions),
                        lexical_decision(mutated_state, mutated_questions),
                    )

    def test_command_emits_explicit_non_neural_evidence_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            outfile = Path(d) / "lexical.json"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    main(["--presentations", "4", "--output", str(outfile)]), 0
                )
            receipt = json.loads(outfile.read_text())
            self.assertEqual(
                json.loads(output.getvalue())["status"],
                "post_hoc_negative_control_only",
            )
            self.assertEqual(receipt["presentations"], 4)
            self.assertEqual(
                receipt["source_verification"],
                "manifest_bytes_only_unless_external_checkout_explicitly_verified",
            )
            first = outfile.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["--presentations", "4", "--output", str(outfile)]), 0
                )
            self.assertEqual(outfile.read_bytes(), first)

    def test_wrong_corpus_fails_and_output_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "altered.json"
            data = json.loads(CASES.read_text())
            data["tasks"][0]["gold"] = "D" if data["tasks"][0]["gold"] != "D" else "A"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "unregistered"):
                main(["--manifest", str(path)])
            link = Path(d) / "link.json"
            target = Path(d) / "target.json"
            target.write_text("retain-original")
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                main(["--output", str(link)])
            self.assertEqual(target.read_text(), "retain-original")


if __name__ == "__main__":
    unittest.main()
