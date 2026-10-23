"""Adversarial source/answer/cost contracts for the nine-arm prospective gate.

These tests use fabricated fixtures only to exercise refusal. They are NOT
original model generations or evidence of memory-quality improvement.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from memory_nine_arm_gate import (
    ARMS, PROFILE, Refused, audit, canonical, create_only, independent_components,
    sha, validate_plan,
)


def h(s):
    return sha(s.encode())


def fixture():
    common = {
        "reader_sha256": h("reader"), "tokenizer_sha256": h("tokenizer"),
        "prompt_sha256": h("prompt"), "encoder_sha256": h("encoder"),
        "source_frontier_sha256": h("source-frontier"),
        "forget_frontier_sha256": h("forget-frontier"),
        "max_context_tokens": 256, "max_generated_tokens": 48,
        "max_evidence_slots": 4, "training_roots": ["train:root"],
        "calibration_roots": ["calib:root"],
    }
    arms = {}
    for arm, profile in ARMS.items():
        trained = arm in "EFGHI"
        arms[arm] = {
            "profile": profile, "artifact_sha256": h("artifact:" + arm),
            "training_receipt_sha256": h("train:" + arm),
            "trained_heads": (1 if arm == "E" else 2) if trained else 0,
            "head_parameters": 1536 if trained else 0,
            "head_optimizer_steps": 20 if trained else 0,
            "head_optimizer_examples": 160 if trained else 0,
            "total_training_budget_units": 500 if trained else 0,
            "max_head_calls": (2 if arm == "F" else 1) if trained else 0,
            "resident_budget_bytes": 8192,
        }
    cases = []
    for i in range(4):
        cases.append({
            "id": "case:%d" % i, "family_id": "family:%d" % i,
            "window": "future_a" if i < 2 else "future_b",
            "question_sha256": h("question:%d" % i),
            "snapshot_sha256": h("snapshot:%d" % i),
            "source_roots": ["root:%d" % i],
            "eligible_source_ids": ["source:%d" % i],
        })
    plan = {
        "schema": PROFILE, "common": common, "arms": arms, "cases": cases,
        "policy": {"alpha": .05, "min_independent_future_groups": 200,
                   "min_independent_groups_per_future_window": 2,
                   "max_candidate_cpu_ratio": 2.0,
                   "max_candidate_rss_ratio": 2.0},
    }
    observations, judgments = [], []
    for case in cases:
        for arm in ARMS:
            answer = "Original test text [E1]"
            observations.append({
                "case_id": case["id"], "arm": arm, "status": "answered",
                "question_sha256": case["question_sha256"],
                "snapshot_sha256": case["snapshot_sha256"],
                "source_frontier_sha256": common["source_frontier_sha256"],
                "forget_frontier_sha256": common["forget_frontier_sha256"],
                "reader_sha256": common["reader_sha256"],
                "tokenizer_sha256": common["tokenizer_sha256"],
                "prompt_sha256": common["prompt_sha256"],
                "encoder_sha256": common["encoder_sha256"],
                "artifact_sha256": arms[arm]["artifact_sha256"],
                "selected_source_ids": case["eligible_source_ids"],
                "context_sha256": h("original context:" + case["id"]),
                "context_tokens": 50, "generated_tokens": 5,
                "answer": answer, "answer_sha256": sha(answer.encode()),
                "worker_receipt_sha256": h("worker:" + case["id"] + arm),
                "reader_calls": 1, "head_calls": 1 if arm in "EFGHI" else 0,
                "latency_ns": 1000, "cpu_ns": 900,
                "peak_rss_bytes": 4096,
            })
            judgments.append({
                "case_id": case["id"], "arm": arm,
                "answer_sha256": sha(answer.encode()),
                "judge_receipt_sha256": h("blind review:" + case["id"] + arm),
                "judge_id": "reviewer:separate",
                "gold_status": "scorable",
                "gold_support_ids": case["eligible_source_ids"],
                "category": "multi_hop" if int(case["id"][-1]) % 2 else "single_hop",
                "correct": True, "grounded": True,
                "semantic_citation_entailment": True,
                "proper_abstention": False, "unsafe": False,
            })
    return plan, observations, judgments


def check(plan, observations, judgments):
    return audit(plan, observations, judgments, sha(canonical(plan)))


class NineArmGateTests(unittest.TestCase):
    def test_full_census_fixture_must_hold(self):
        plan, obs, judges = fixture()
        report = check(plan, obs, judges)
        self.assertEqual(report["planned_cases"], 4)
        self.assertEqual(report["original_Reader_attempts"], 36)
        self.assertEqual(report["effective_future_source_components"], 4)
        self.assertEqual(report["status"], "HOLD_NO_GO")
        self.assertFalse(report["production_accepted"])
        self.assertFalse(report["superiority_established"])

    def test_missing_original_attempt_refused(self):
        p, o, j = fixture()
        with self.assertRaises(Refused):
            check(p, o[1:], j)

    def test_missing_blind_judgment_refused(self):
        p, o, j = fixture()
        with self.assertRaises(Refused):
            check(p, o, j[1:])

    def test_duplicate_observation_refused(self):
        p, o, j = fixture()
        o[0] = copy.deepcopy(o[1])
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_changed_original_reader_refused(self):
        p, o, j = fixture()
        o[0]["reader_sha256"] = h("wrong model")
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_stale_forget_frontier_refused(self):
        p, o, j = fixture()
        o[0]["forget_frontier_sha256"] = h("stale")
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_changed_query_hash_refused(self):
        p, o, j = fixture()
        o[0]["question_sha256"] = h("another query")
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_unknown_source_refused(self):
        p, o, j = fixture()
        o[0]["selected_source_ids"] = ["unavailable"]
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_orphan_citation_refused(self):
        p, o, j = fixture()
        o[0]["answer"] = "Unsupported [E2]"
        o[0]["answer_sha256"] = sha(o[0]["answer"].encode())
        j[0]["answer_sha256"] = o[0]["answer_sha256"]
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_malformed_citation_refused(self):
        p, o, j = fixture()
        o[0]["answer"] = "Unsupported [Ex]"
        o[0]["answer_sha256"] = sha(o[0]["answer"].encode())
        j[0]["answer_sha256"] = o[0]["answer_sha256"]
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_modified_original_answer_refused(self):
        p, o, j = fixture()
        o[0]["answer"] = "Altered [E1]"
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_wrong_independent_answer_refused(self):
        p, o, j = fixture()
        j[0]["answer_sha256"] = h("different")
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_gold_changed_between_arms_refused(self):
        p, o, j = fixture()
        j[0]["gold_status"] = "missing"
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_forged_boolean_refused(self):
        p, o, j = fixture()
        j[0]["correct"] = 1
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_selected_head_overbudget_refused(self):
        p, o, j = fixture()
        row = next(x for x in o if x["arm"] == "G")
        row["head_calls"] = 2
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_mismatched_training_capacity_refused(self):
        p, o, j = fixture()
        p["arms"]["F"]["head_parameters"] += 1
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_unmatched_evolution_continuation_refused(self):
        p, o, j = fixture()
        p["arms"]["I"]["head_optimizer_steps"] += 1
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_training_holdout_leak_refused(self):
        p, o, j = fixture()
        p["common"]["training_roots"].append("root:0")
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_cross_window_source_reuse_refused(self):
        p, o, j = fixture()
        p["cases"][2]["source_roots"] = ["root:0"]
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_shared_ancestors_reduce_effective_n(self):
        p, o, j = fixture()
        p["cases"][1]["source_roots"] = ["root:0"]
        self.assertEqual(len(independent_components(validate_plan(p), "future_a")), 1)
        report = check(p, o, j)
        self.assertEqual(report["effective_future_source_components"], 3)

    def test_source_first_gold_cannot_enter_plan(self):
        p, o, j = fixture()
        p["cases"][0]["category"] = "multi_hop"
        with self.assertRaises(Refused):
            check(p, o, j)

    def test_plan_sha_pin_refused_after_mutation(self):
        p, o, j = fixture()
        original_pin = sha(canonical(p))
        p["policy"]["max_candidate_cpu_ratio"] = 100.0
        with self.assertRaises(Refused):
            audit(p, o, j, original_pin)

    def test_unavailable_original_is_counted_not_forged(self):
        p, o, j = fixture()
        o[0]["status"] = "unavailable"
        o[0]["answer"] = ""
        o[0]["answer_sha256"] = sha(b"")
        o[0]["generated_tokens"] = 0
        o[0]["reader_calls"] = 0
        j[0]["answer_sha256"] = sha(b"")
        j[0]["correct"] = False
        j[0]["grounded"] = False
        j[0]["semantic_citation_entailment"] = False
        result = check(p, o, j)
        self.assertFalse(result["task_safety_gate"])
        self.assertEqual(result["per_arm"]["A"]["unavailable_count"], 1)

    def test_create_only_output_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.json"
            create_only(path, {"status": "HOLD_NO_GO"})
            with self.assertRaises(FileExistsError):
                create_only(path, {"status": "PASS"})
            self.assertEqual(json.loads(path.read_text())["status"], "HOLD_NO_GO")

    def test_negative_control_all_nine_equal_never_positive(self):
        p, o, j = fixture()
        result = check(p, o, j)
        self.assertEqual(result["contrasts"]["candidate_vs_hybrid"]["delta"], 0)
        self.assertFalse(result["descriptive_quality_gate"])


if __name__ == "__main__":
    unittest.main()
