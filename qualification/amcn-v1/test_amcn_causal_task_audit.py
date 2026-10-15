"""Synthetic *mechanism only* adversarial tests; never count as Reader calls."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

import amcn_causal_task_audit as a


def sha(text):
    return sha256(text.encode("utf-8")).hexdigest()


def fixture():
    plans = {
        "profile": a.PROFILE,
        "reader_sha256": sha("frozen-real-reader-not-in-this-fixture"),
        "tokenizer_sha256": sha("fixed-tokenizer"),
        "prompt_sha256": sha("fixed-prompt"),
        "encoder_receipt_sha256": sha("fixture-no-physical-pretrained-encoder"),
        "max_input_tokens": 1024, "max_output_tokens": 128,
        "capacity": {
            name: {"total_trainable_parameters": 2048, "optimizer_steps": 40,
                   "minibatch_examples": 320, "artifact_sha256": sha(name + "-bank"),
                   "training_receipt_sha256": sha(name + "-no-real-training"),
                   "head_sha256_by_type": {kind: sha(name + "-" + kind)
                      for kind in a.TYPES},
                   "trainable_head_count": 2, "active_heads_per_query": 1}
            for name in ("shared", "typed")},
        "cases": [], "lineage_alias_edges": [],
        "future_calendar_verified": False, "production_accepted": False,
    }
    specs = [
        ("select", "episodic", "a"),
        ("retention", "semantic", "b"),
        ("future_a", "episodic", "c"),
        ("future_a", "semantic", "d"),
        ("future_b", "episodic", "e"),
        ("future_b", "semantic", "f"),
    ]
    for i, (split, kind, root) in enumerate(specs):
        sources = [{"source_id": f"{root}-s{j}", "revision": 1,
                    "content_sha256": sha(f"raw source {root}:{j}"),
                    "text": f"raw source {root}:{j}"} for j in range(3)]
        choices = {}
        for arm in a.ARMS:
            graph = None
            if arm in ("typed_fixed_graph", "typed_learned_graph",
                       "typed_graph_lesion", "unsplit_equal_graph"):
                graph = sha("fixed-graph" if arm == "typed_fixed_graph"
                            else "lesion-graph" if arm == "typed_graph_lesion"
                            else "learned-graph")
            head = (None if arm == "strong_hybrid_rag" else
                    sha("frozen") if arm == "frozen_shared" else
                    sha("shared-" + kind) if arm in ("learned_shared", "unsplit_equal_graph") else
                    sha("typed-" + ("semantic" if kind == "episodic"
                                    else "episodic")) if arm == "typed_swapped"
                    else sha("typed-" + kind))
            route = (None if arm in ("strong_hybrid_rag", "frozen_shared",
                                          "learned_shared", "unsplit_equal_graph")
                     else ("semantic" if kind == "episodic"
                           else "episodic") if arm == "typed_swapped" else kind)
            choices[arm] = {"source_ids": [sources[0]["source_id"]] if not graph
                            else [sources[1]["source_id"]],
                            "head_sha256": head, "graph_sha256": graph,
                            "route_type": route, "planned_request_sha256": ""}
        case = {"question_id": f"q{i}", "family": f"family-{root}",
                "source_root": root, "memory_type": kind, "split": split,
                "scope": "test-private", "generation": "test-g1",
                "question": f"Question {i}?", "sources": sources,
                "source_frontier_sha256": a.digest(sorted(
                    sources, key=lambda s: s["source_id"])),
                "arm_plans": choices}
        plans["cases"].append(case)
        for arm in a.ARMS:
            choices[arm]["planned_request_sha256"] = a.request_digest(
                plans, case, arm, {s["source_id"]: s for s in sources})
    answers, judgments = [], []
    for case in plans["cases"]:
        for arm in a.ARMS:
            raw = "synthetic test-only answer " + arm
            answers.append({"question_id": case["question_id"], "arm": arm,
                            "request_sha256": case["arm_plans"][arm]["planned_request_sha256"],
                            "status": "ok", "raw_answer": raw,
                            "raw_answer_sha256": sha(raw),
                            "input_tokens": 128, "output_tokens": 8,
                            "wall_ms": 22, "emitted_source_ids": [],
                            "reader_execution_receipt_sha256": sha("synthetic-execution")})
            judgments.append({"question_id": case["question_id"], "arm": arm,
                              "raw_answer_sha256": sha(raw),
                              "correctness": int(arm == "typed_learned_graph"),
                              "citation_entailment": None,
                              "review_receipt_sha256": sha("synthetic-non-review")})
    return plans, answers, judgments


class CausalTaskAuditTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.answers, self.judgments = fixture()

    def score(self):
        return a.audit(self.plan, self.answers, self.judgments)

    def test_complete_synthetic_mechanism_cannot_promote(self):
        result = self.score()
        self.assertEqual(result["question_count"], 6)
        self.assertEqual(result["original_answer_attempts"], 54)
        self.assertEqual(result["future_group_count_upper_bound"], 4)
        self.assertEqual(result["paired_causal_diagnostics"]["graph_vs_strong_rag"]
                         ["mean_paired_success_delta"], 1)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["superiority_claim"])
        self.assertIsNone(result["citation_precision"])

    def test_missing_or_duplicate_arm_denied(self):
        self.answers.pop()
        with self.assertRaises(a.Refused):
            self.score()
        self.answers = fixture()[1]
        self.answers[-1] = deepcopy(self.answers[0])
        with self.assertRaises(a.Refused):
            self.score()

    def test_missing_second_unspecialized_head_denied(self):
        shared = self.plan["capacity"]["shared"]
        shared["head_sha256_by_type"]["semantic"] = shared[
            "head_sha256_by_type"]["episodic"]
        with self.assertRaisesRegex(a.Refused, "two independent physical Heads"):
            self.score()

    def test_wrong_pooled_head_assignment_denied(self):
        case = self.plan["cases"][0]
        case["arm_plans"]["learned_shared"]["head_sha256"] = sha("wrong-shared-head")
        # Even a coherently rewritten request digest cannot substitute a third
        # unmetered Head for the original pooled equal-capacity control.
        case["arm_plans"]["learned_shared"]["planned_request_sha256"] = a.request_digest(
            self.plan, case, "learned_shared", {s["source_id"]: s for s in case["sources"]})
        with self.assertRaisesRegex(a.Refused, "physical Head bank"):
            self.score()

    def test_extra_per_question_active_head_denied(self):
        self.plan["capacity"]["typed"]["active_heads_per_query"] = 2
        with self.assertRaisesRegex(a.Refused, "one read per query"):
            self.score()

    def test_training_budget_not_equal_denied(self):
        self.plan["capacity"]["typed"]["optimizer_steps"] += 1
        with self.assertRaisesRegex(a.Refused, "capacity"):
            self.score()

    def test_source_byte_tamper_denied(self):
        self.plan["cases"][0]["sources"][0]["text"] = "different"
        with self.assertRaisesRegex(a.Refused, "source"):
            self.score()

    def test_source_revision_drift_denied(self):
        self.plan["cases"][0]["sources"][0]["revision"] += 1
        with self.assertRaises(a.Refused):
            self.score()

    def test_read_model_or_prompt_rebind_denied(self):
        self.plan["reader_sha256"] = sha("new Reader")
        with self.assertRaisesRegex(a.Refused, "request"):
            self.score()

    def test_type_swapping_must_change_head(self):
        case = self.plan["cases"][0]
        case["arm_plans"]["typed_swapped"]["head_sha256"] = case[
            "arm_plans"]["learned_typed"]["head_sha256"]
        case["arm_plans"]["typed_swapped"]["planned_request_sha256"] = a.request_digest(
            self.plan, case, "typed_swapped", {s["source_id"]: s for s in case["sources"]})
        with self.assertRaisesRegex(a.Refused, "physical Head bank"):
            self.score()

    def test_graph_weight_fork_must_keep_head_fixed(self):
        case = self.plan["cases"][0]
        case["arm_plans"]["typed_fixed_graph"]["head_sha256"] = sha("secret extra capacity")
        case["arm_plans"]["typed_fixed_graph"]["planned_request_sha256"] = a.request_digest(
            self.plan, case, "typed_fixed_graph", {s["source_id"]: s for s in case["sources"]})
        with self.assertRaisesRegex(a.Refused, "changed learned typed Head"):
            self.score()

    def test_graph_lesion_must_differ(self):
        case = self.plan["cases"][0]
        case["arm_plans"]["typed_graph_lesion"]["graph_sha256"] = case[
            "arm_plans"]["typed_learned_graph"]["graph_sha256"]
        case["arm_plans"]["typed_graph_lesion"]["planned_request_sha256"] = a.request_digest(
            self.plan, case, "typed_graph_lesion", {s["source_id"]: s for s in case["sources"]})
        with self.assertRaisesRegex(a.Refused, "distinct interventions"):
            self.score()

    def test_answer_substitution_denied(self):
        self.answers[0]["raw_answer"] = "edited after generating"
        with self.assertRaisesRegex(a.Refused, "modified answer"):
            self.score()

    def test_revised_answer_not_matching_judgment_denied(self):
        self.judgments[0]["raw_answer_sha256"] = sha("different answer")
        with self.assertRaisesRegex(a.Refused, "judgment"):
            self.score()

    def test_failed_reader_attempt_kept_and_scored_zero(self):
        self.answers[0]["status"] = "failed"
        self.answers[0]["raw_answer"] = None
        self.answers[0]["raw_answer_sha256"] = None
        self.answers[0]["reader_execution_receipt_sha256"] = None
        self.judgments[0]["raw_answer_sha256"] = None
        self.judgments[0]["correctness"] = 0
        self.assertEqual(self.score()["scores"]["strong_hybrid_rag"]["failed_generations"], 1)
        self.judgments[0]["correctness"] = 1
        with self.assertRaisesRegex(a.Refused, "failed model generation"):
            self.score()

    def test_token_budget_denied(self):
        self.answers[0]["input_tokens"] = 999999
        with self.assertRaisesRegex(a.Refused, "tokens"):
            self.score()

    def test_orphan_citation_is_not_100pct_precision(self):
        raw = "synthetic original [E41]"
        self.answers[0]["raw_answer"] = raw
        self.answers[0]["raw_answer_sha256"] = sha(raw)
        self.judgments[0]["raw_answer_sha256"] = sha(raw)
        self.answers[0]["emitted_source_ids"] = ["UNDELIVERED:[E41]"]
        result = self.score()
        self.assertEqual(result["matched_resource_observations"]["strong_hybrid_rag"]
                         ["undelivered_citation_ids"], 1)
        self.assertIsNone(result["citation_precision"])

    def test_manufactured_citation_label_denied(self):
        self.answers[0]["emitted_source_ids"] = ["invented"]
        with self.assertRaisesRegex(a.Refused, "disagree with raw"):
            self.score()

    def test_omitted_raw_orphan_citation_denied(self):
        raw = "original text [E5]"
        self.answers[0]["raw_answer"] = raw
        self.answers[0]["raw_answer_sha256"] = sha(raw)
        self.judgments[0]["raw_answer_sha256"] = sha(raw)
        self.answers[0]["emitted_source_ids"] = []
        with self.assertRaisesRegex(a.Refused, "disagree with raw"):
            self.score()

    def test_retention_isolated_from_future_source_family(self):
        self.plan["lineage_alias_edges"] = [["b", "c"]]
        with self.assertRaisesRegex(a.Refused, "retention"):
            self.score()

    def test_exact_original_pilot_type_inventory(self):
        self.assertEqual(a.TYPES, ("episodic", "semantic"))
        self.assertEqual({c["memory_type"] for c in self.plan["cases"]},
                         {"episodic", "semantic"})
        self.assertEqual(self.score()["question_count"], 6)

    def test_no_admissible_future_without_both_windows(self):
        self.plan["cases"][4]["split"] = "future_a"
        self.plan["cases"][5]["split"] = "future_a"
        with self.assertRaises(a.Refused):
            self.score()

    def test_alias_chain_reduces_effective_n(self):
        self.plan["lineage_alias_edges"] = [["c", "d"]]
        outcome = self.score()
        self.assertEqual(outcome["future_group_count_upper_bound"], 3)
        self.assertEqual(outcome["transitive_source_family_groups_upper_bound"], 5)

    def test_cross_future_partition_transitive_alias_denied(self):
        self.plan["lineage_alias_edges"] = [["c", "d"], ["d", "e"]]
        with self.assertRaisesRegex(a.Refused, "transitive leakage"):
            self.score()

    def test_prospective_claims_denied(self):
        self.plan["future_calendar_verified"] = True
        with self.assertRaisesRegex(a.Refused, "future time"):
            self.score()

    def test_label_or_answer_leaked_to_plan_denied(self):
        self.plan["cases"][0]["gold_answer"] = "label"
        with self.assertRaisesRegex(a.Refused, "complete"):
            self.score()

    def test_exact_original_sha_pins_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "case.json"
            raw = a.canonical(self.plan) + b"\n"
            p.write_bytes(raw)
            self.assertEqual(a.pinned_json(p, sha256(raw).hexdigest()), self.plan)
            with self.assertRaisesRegex(a.Refused, "changed"):
                a.pinned_json(p, sha("wrong"))
            p.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaisesRegex(a.Refused, "duplicate"):
                a.pinned_json(p, sha256(p.read_bytes()).hexdigest())

    def test_nonfinite_scores_denied(self):
        self.judgments[0]["correctness"] = float("nan")
        with self.assertRaises(a.Refused):
            self.score()

    def test_model_receipt_missing_denied(self):
        self.answers[0]["reader_execution_receipt_sha256"] = None
        with self.assertRaisesRegex(a.Refused, "physical inference"):
            self.score()


if __name__ == "__main__":
    unittest.main()
