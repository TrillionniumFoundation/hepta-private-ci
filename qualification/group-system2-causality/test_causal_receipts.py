"""Adversarial, standard-library-only Group causality contract regressions."""

from copy import deepcopy
import json
import unittest

from causal_receipts import (
    ReceiptError, parse_json_strict, seal_execution,
    seal_postscore, seal_predecision,
)


def h(char: str) -> str:
    return char * 64


def sample():
    pre = {
        "phase": "PREDECISION", "run_id": "run.7", "source_cluster_id": "source.7",
        "seed": 7, "actor_id": "actor.1", "evaluator_id": "reviewer.1",
        "encoder_digest": h("1"), "encoder_generation": 3,
        "input_digest": h("2"), "policy_digest": h("3"),
        "source_frontier_digest": h("4"), "candidate_ids": ["cell.memory", "cell.logic"],
        "allowed_actions": ["RECALL", "VERIFY", "STOP", "ABSTAIN"],
        "hard_cost_cap": 10, "max_depth": 8, "emission_reserve": 1,
        "required_outputs": ["answer"],
    }
    pre_sha = seal_predecision(pre)["predecision_digest"]
    execute = {"phase": "EXECUTED", "pre_digest": pre_sha,
               "steps": [
                   {"index": 0, "action": "RECALL", "candidate_id": "cell.memory",
                    "cost": 2, "observation_digest": h("5"), "status": "COMPLETE"},
                   {"index": 1, "action": "VERIFY", "candidate_id": "cell.logic",
                    "cost": 3, "observation_digest": h("6"), "status": "COMPLETE"},
                   {"index": 2, "action": "STOP", "candidate_id": "cell.logic",
                    "cost": 0, "observation_digest": h("7"), "status": "COMPLETE"},
               ],
               "outputs": [{"kind": "answer", "digest": h("8"), "cost": 1}],
               "terminal_action": "STOP"}
    exe_sha = seal_execution(pre, execute)["execution_digest"]
    post = {"phase": "POSTSCORE", "pre_digest": pre_sha,
            "execution_digest": exe_sha, "evaluator_id": "reviewer.1",
            "outcome_digest": h("9"), "independent_evidence_digest": h("a"),
            "quality": 0.8, "severe": False, "completed": True,
            "reported_cost": 6}
    return pre, execute, post


class CausalReceiptTests(unittest.TestCase):
    def test_three_phase_positive_and_immutable_receipts(self):
        pre, exe, post = sample()
        a, b, c = seal_predecision(pre), seal_execution(pre, exe), seal_postscore(pre, exe, post)
        self.assertEqual(a, seal_predecision(pre))
        self.assertEqual(b, seal_execution(pre, exe))
        self.assertEqual(c, seal_postscore(pre, exe, post))
        self.assertEqual(b["physical_cost_claim"], 6)
        self.assertTrue(b["complete_outputs"])
        self.assertFalse(c["production_promotion_authorized"])
        self.assertEqual(c["authority"], "DENY_ALL")

    def test_terminal_truth_cannot_enter_predecision(self):
        pre, _, _ = sample()
        pre["outcome_digest"] = h("a")
        with self.assertRaises(ReceiptError):
            seal_predecision(pre)

    def test_future_label_cannot_enter_plan(self):
        pre, _, _ = sample()
        pre["quality"] = 1.0
        with self.assertRaises(ReceiptError):
            seal_predecision(pre)

    def test_future_seal_cannot_change_input_or_generation(self):
        pre, exe, _ = sample()
        pre["encoder_generation"] += 1
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)

    def test_actor_cannot_score_their_own_decision(self):
        pre, _, _ = sample()
        pre["evaluator_id"] = pre["actor_id"]
        with self.assertRaises(ReceiptError):
            seal_predecision(pre)

    def test_reject_unsealed_episode(self):
        pre, exe, _ = sample()
        exe["pre_digest"] = h("f")
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)

    def test_reject_steps_after_stop(self):
        pre, exe, _ = sample()
        exe["steps"][1]["action"] = "STOP"
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)

    def test_reject_but_account_failed_verifier(self):
        pre, exe, post = sample()
        exe["steps"][1]["status"] = "FAILED"
        seal = seal_execution(pre, exe)
        self.assertFalse(seal["complete_outputs"])
        self.assertEqual(seal["physical_cost_claim"], 6)
        post.update(execution_digest=seal["execution_digest"], quality=0.0,
                    severe=True, completed=False)
        self.assertFalse(seal_postscore(pre, exe, post)["completed"])
        post["quality"] = 0.1
        with self.assertRaises(ReceiptError):
            seal_postscore(pre, exe, post)

    def test_reject_overbudget_work(self):
        pre, exe, _ = sample()
        exe["steps"][1]["cost"] = 9
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)

    def test_reject_unregistered_action_or_candidate(self):
        pre, exe, _ = sample()
        exe["steps"][1]["candidate_id"] = "cell.fake"
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)
        exe["steps"][1]["candidate_id"] = "cell.logic"
        exe["steps"][1]["action"] = "SOLVE_SECRET"
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)

    def test_reject_missing_required_output_claim(self):
        pre, exe, post = sample()
        exe["outputs"] = []
        sealed = seal_execution(pre, exe)
        self.assertFalse(sealed["complete_outputs"])
        post["execution_digest"] = sealed["execution_digest"]
        with self.assertRaises(ReceiptError):
            seal_postscore(pre, exe, post)
        post.update(completed=False, quality=0.0, severe=True, reported_cost=5)
        self.assertFalse(seal_postscore(pre, exe, post)["completed"])

    def test_abstain_is_explicit_and_never_emits_output(self):
        pre, exe, _ = sample()
        exe["steps"][-1]["action"] = "ABSTAIN"
        exe["terminal_action"] = "ABSTAIN"
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)
        exe["outputs"] = []
        self.assertFalse(seal_execution(pre, exe)["complete_outputs"])

    def test_untrusted_cost_mismatch_rejected(self):
        pre, exe, post = sample()
        post["reported_cost"] = 5
        with self.assertRaises(ReceiptError):
            seal_postscore(pre, exe, post)

    def test_score_wrong_phase_or_observer_rejected(self):
        pre, exe, post = sample()
        post["phase"] = "PREDECISION"
        with self.assertRaises(ReceiptError):
            seal_postscore(pre, exe, post)
        post["phase"] = "POSTSCORE"
        post["evaluator_id"] = "actor.1"
        with self.assertRaises(ReceiptError):
            seal_postscore(pre, exe, post)

    def test_output_hash_swap_is_detected_at_postscore(self):
        pre, exe, post = sample()
        exe["outputs"][0]["digest"] = h("b")
        with self.assertRaises(ReceiptError):
            seal_postscore(pre, exe, post)

    def test_output_emission_is_paid(self):
        pre, exe, post = sample()
        self.assertEqual(seal_execution(pre, exe)["physical_cost_claim"], 6)
        self.assertEqual(seal_postscore(pre, exe, post)["cost_units"], 6)

    def test_zero_cost_output_rejected(self):
        pre, exe, _ = sample()
        exe["outputs"][0]["cost"] = 0
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)

    def test_output_reserve_cannot_be_spent_on_reasoning(self):
        pre, exe, _ = sample()
        pre["hard_cost_cap"] = 5
        exe["pre_digest"] = seal_predecision(pre)["predecision_digest"]
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)

    def test_decoder_cost_cannot_exceed_remaining_budget(self):
        pre, exe, _ = sample()
        exe["outputs"][0]["cost"] = 6
        with self.assertRaises(ReceiptError):
            seal_execution(pre, exe)

    def test_reserved_output_cost_is_preregistered_and_sufficient(self):
        pre, _, _ = sample()
        pre["emission_reserve"] = 0
        with self.assertRaises(ReceiptError):
            seal_predecision(pre)
        pre["emission_reserve"] = 2
        pre["required_outputs"] = ["answer", "audio", "video"]
        with self.assertRaises(ReceiptError):
            seal_predecision(pre)

    def test_strict_json_rejects_ambiguous_keys_and_nan(self):
        with self.assertRaises(ReceiptError):
            parse_json_strict('{"phase":"PREDECISION","phase":"POSTSCORE"}')
        with self.assertRaises(ReceiptError):
            parse_json_strict('{"score":NaN}')
        with self.assertRaises(ReceiptError):
            parse_json_strict('[0]')
        self.assertEqual(parse_json_strict('{"x":1}'), {"x": 1})

    def test_reject_negative_bool_zero_stem_and_duplicate_candidate(self):
        pre, _, _ = sample()
        cases = [
            ("seed", True), ("encoder_generation", 0),
            ("encoder_digest", "0" * 64),
            ("candidate_ids", ["cell.logic", "cell.logic"]),
            ("allowed_actions", ["STOP", "ABSTAIN", "RECALL"]),
        ]
        for name, value in cases:
            with self.subTest(name=name):
                candidate = deepcopy(pre)
                candidate[name] = value
                with self.assertRaises(ReceiptError):
                    seal_predecision(candidate)

    def test_score_rejects_invalid_numbers_and_flags(self):
        pre, exe, post = sample()
        cases = [("quality", float("nan")), ("quality", True),
                 ("quality", 1.1), ("completed", 1), ("severe", 0)]
        for name, value in cases:
            with self.subTest(name=name, value=str(value)):
                p = deepcopy(post)
                p[name] = value
                with self.assertRaises(ReceiptError):
                    seal_postscore(pre, exe, p)


if __name__ == "__main__":
    unittest.main()
