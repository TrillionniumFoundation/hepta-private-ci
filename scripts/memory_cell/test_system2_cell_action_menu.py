"""Exact bound, no-label-leak and sealed synthetic replay tests."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import system2_cell_action_menu as menu
from system2_cell_support_gate import ABSTAIN, EVAL_POSITIONS


def fake_rows():
    data = []
    for index in range(menu.QUESTION_IDS):
        qid = "onehop:fixture" + str(index)
        device = "DEV-" + format(index, "07X")
        target = "TAG-" + format(index, "07X")
        competitor = "TAG-" + format(index + 100, "07X")
        for arm, view in EVAL_POSITIONS:
            supported = arm in menu.SUPPORTED_ARMS
            facts = (
                [(device, target), ("DEV-000FFFF", competitor)]
                if supported
                else [("DEV-000FFFF", competitor)]
                if arm == "decoy_only"
                else []
            )
            # A held-out test subject for which the E-labeled presentation,
            # but not unlabeled presentation, happens to return the answer.
            correct = supported and (
                view == "unlabeled" and index != 0 or view == "e_label" and index == 0
            )
            answer = (
                target if correct else ABSTAIN if arm == "no_evidence" else competitor
            )
            data.append(
                dict(
                    qid=qid,
                    arm=arm,
                    view=view,
                    matched_facts=facts,
                    question_device=device,
                    sources=0 if arm == "no_evidence" else (2 if supported else 1),
                    reader_answer=answer,
                    reader_cost_ns=100 + index,
                    input_tokens=35,
                    generated_tokens=8,
                    support=supported,
                    target=target,
                )
            )
    assert len(data) == 200
    return data


class ActionMenuTests(unittest.TestCase):
    def setUp(self):
        self.rows = fake_rows()
        self.actions = [menu.static_action(menu.visible(r)) for r in self.rows]

    def test_no_privileged_fields_reach_static_decision(self):
        sample = self.rows[0]
        observation = menu.visible(sample)
        self.assertNotIn("target", observation)
        self.assertNotIn("reader_answer", observation)
        self.assertNotIn("reader_cost_ns", observation)
        self.assertEqual(
            set(observation),
            {"qid", "arm", "view", "question_device", "matched_facts", "sources"},
        )
        with self.assertRaises(ValueError):
            menu.static_action(observation | {"target": sample["target"]})

    def test_mutated_model_answer_or_gold_does_not_change_frozen_actions(self):
        before = [menu.static_action(menu.visible(r)) for r in self.rows]
        wrong = copy.deepcopy(self.rows)
        for r in wrong:
            r["reader_answer"] = "unrelated"
            r["target"] = "TAG-FAKEABC"
            r["reader_cost_ns"] = 999999
        self.assertEqual(before, [menu.static_action(menu.visible(r)) for r in wrong])

    def test_perfect_information_binary_menu_matches_exact_nonlearning_rule(self):
        result = menu.review(self.rows, self.actions)
        self.assertEqual(
            result["frozen_source_match_correct"],
            result["perfect_information_call_stop_ceiling"],
        )
        self.assertEqual(result["learned_gate_action_menu_headroom"], 0)
        self.assertEqual(result["reader_calls_simulated_by_frozen_gate"], 120)
        self.assertEqual(result["always_abstain_correct"], 80)
        self.assertEqual(result["closed_grammar_symbolic_correct"], 200)

    def test_alternative_views_could_have_limited_posthoc_headroom(self):
        result = menu.review(self.rows, self.actions)
        self.assertEqual(result["positive_order_cases"], 40)
        self.assertEqual(result["fixed_unlabeled_positive_correct"], 38)
        self.assertEqual(result["postseal_any_of_three_views_correct"], 40)
        self.assertEqual(result["postseal_view_menu_headroom"], 2)
        self.assertTrue(result["postseal_view_oracle_was_never_an_online_action"])
        self.assertTrue(result["all_historical_view_inferences_paid"])

    def test_duplicate_missing_and_changed_actions_fail_closed(self):
        for changed in (
            self.actions[:-1],
            self.actions + [self.actions[0]],
            [self.actions[0]] * len(self.actions),
        ):
            with self.assertRaises(ValueError):
                menu.review(self.rows, changed)
        changed = copy.deepcopy(self.actions)
        changed[0]["closed_grammar_response"] = "TAG-FAKEABC"
        with self.assertRaisesRegex(ValueError, "changed"):
            menu.review(self.rows, changed)

    def test_wrong_gold_after_sealing_makes_symbolic_control_fail(self):
        rows = copy.deepcopy(self.rows)
        changed_qid = rows[0]["qid"]
        for row in rows:
            if row["qid"] == changed_qid:
                row["target"] = "TAG-FAKEABC"
        result = menu.review(rows, self.actions)
        self.assertEqual(result["closed_grammar_symbolic_correct"], 194)
        self.assertEqual(result["learned_gate_action_menu_headroom"], 0)

    def test_changed_reader_cost_detected(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["reader_cost_ns"] = -1
        with self.assertRaisesRegex(ValueError, "paid"):
            menu.review(rows, self.actions)
        rows[0]["reader_cost_ns"] = True
        with self.assertRaisesRegex(ValueError, "paid"):
            menu.review(rows, self.actions)

    def test_unregistered_view_or_extra_subject_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["view"] = "random_unregistered"
        with self.assertRaises(ValueError):
            menu.review(rows, self.actions)
        rows = copy.deepcopy(self.rows)
        rows[0]["qid"] = "other-question"
        with self.assertRaises(ValueError):
            menu.review(rows, self.actions)

    def test_ambiguous_exact_facts_rejected(self):
        row = copy.deepcopy(self.rows[0])
        row["matched_facts"].append((row["question_device"], "TAG-0000000"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            menu.static_action(menu.visible(row))

    def test_negative_evidence_receives_external_refusal_not_neural_credit(self):
        for r, a in zip(self.rows, self.actions, strict=True):
            if r["arm"] in menu.NEGATIVE_ARMS:
                self.assertEqual(a["closed_grammar_response"], ABSTAIN)
                self.assertFalse(a["frozen_source_match"])
            else:
                self.assertNotEqual(a["closed_grammar_response"], ABSTAIN)
                self.assertTrue(a["frozen_source_match"])

    def test_reproducible_file_seal_and_real_runner(self):
        manifests = {k: dict(sha=v["sha"], files=20) for k, v in menu.PINS.items()}
        snapshots = {k: v for k, v in manifests.items()}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "study"
            with patch.object(
                menu, "prepare", return_value=(snapshots, [{}] * 180, self.rows)
            ):
                result = menu.run({}, out, source_commit="a" * 40)
            self.assertEqual(
                result["perfect_information_call_stop_ceiling"],
                result["frozen_source_match_correct"],
            )
            self.assertEqual(result["true_new_model_calls"], 0)
            self.assertFalse(result["production_accepted"])
            seal = json.loads((out / "action-seal.json").read_text())
            raw = (out / "frozen-actions.jsonl").read_bytes()
            self.assertEqual(
                seal,
                {
                    "rows": 200,
                    "scoring_started": False,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
            )
            self.assertEqual(
                len((out / "frozen-actions.jsonl").read_text().splitlines()), 200
            )
            self.assertNotIn('"reader_answer"', raw.decode())
            self.assertNotIn('"target"', raw.decode())

    def test_runner_incomplete_source_leaves_failure_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fail"
            with patch.object(menu, "prepare", side_effect=ValueError("injected")):
                with self.assertRaises(ValueError):
                    menu.run({}, out, source_commit="a" * 40)
            self.assertFalse((out / "summary.json").exists())
            receipt = json.loads((out / "failure.json").read_text())
            self.assertTrue(receipt["unknown_work_not_free"])

    def test_invalid_commit_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bad"
            with self.assertRaisesRegex(ValueError, "commit"):
                menu.run({}, out, source_commit="not-a-commit")
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
