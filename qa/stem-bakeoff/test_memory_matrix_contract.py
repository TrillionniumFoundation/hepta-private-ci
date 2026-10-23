"""Strict A--I paired-census and negative-control tests, no mocked model claims."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from memory_matrix_contract import ARMS, CONTRASTS, SCHEMA, audit, canonical, digest, freeze_plan


class MemoryMatrixContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pred = self.root / "predictions"
        self.pred.mkdir()
        pin = "a" * 64
        self.roles = {"train": ["train-1"], "calibration": ["cal-1"],
                      "evaluation": ["eval-1", "eval-2"],
                      "future_1": ["future-a", "future-b"],
                      "future_2": ["future-c", "future-d"], "ood": ["ood-1", "ood-2"]}
        self.queries, self.gold = [], []
        for role in ("evaluation", "future_1", "future_2", "ood"):
            for i, group in enumerate(self.roles[role]):
                qid = f"{role}-{i}"
                self.queries.append({"query_id": qid, "group_id": group, "split": role,
                                     "question": f"When did event {qid} happen?",
                                     "available_source_ids": [f"source-{qid}"],
                                     "source_snapshot_sha256": digest(qid.encode())})
                self.gold.append({"query_id": qid, "answerable": i == 0,
                                  "acceptable_answers": ["A fact"] if i == 0 else [],
                                  "required_support_ids": [f"source-{qid}"] if i == 0 else [],
                                  "slice": "multi_hop" if i == 0 else "adversarial"})
        self.plan = {
            "schema": SCHEMA, "suite_id": "memory-ai-matrix-test-v1", "source_sha256": pin,
            "query_sha256": digest(canonical(self.queries)),
            "gold_sha256": digest(canonical(self.gold)), "reader_sha256": "b" * 64,
            "source_frontier_sha256": "c" * 64, "forget_frontier_sha256": "d" * 64,
            "splits": self.roles, "arms": ARMS, "comparisons": [list(x) for x in CONTRASTS],
            "budget": {"top_k": 8, "max_context_bytes": 4096, "max_output_tokens": 64,
                       "max_wall_ms": 2000, "max_peak_rss_bytes": 8000000,
                       "max_resident_bytes": 4000000, "max_head_calls": 8,
                       "max_router_calls": 8, "max_encoder_calls": 8, "max_graph_calls": 8},
            "minimum_independent_groups": 30, "minimum_gain": .03, "seed": 20261023,
        }
        self.predictions = {}
        self.save_all()
        for arm in ARMS:
            self.predictions[arm] = []
            for q in self.queries:
                answerable = q["query_id"].endswith("-0")
                self.predictions[arm].append({
                    "arm": arm, "query_id": q["query_id"],
                    "plan_sha256": digest(canonical(self.plan)),
                    "source_snapshot_sha256": q["source_snapshot_sha256"],
                    "source_frontier_sha256": self.plan["source_frontier_sha256"],
                    "forget_frontier_sha256": self.plan["forget_frontier_sha256"],
                    "reader_sha256": self.plan["reader_sha256"],
                    "selected_source_ids": [f"source-{q['query_id']}"] if answerable else [],
                    "abstained": not answerable, "answer": "A fact" if answerable else "",
                    "resources": {"wall_ms": 4.0, "peak_rss_bytes": 1024,
                                  "resident_bytes": 512, "context_bytes": 100,
                                  "input_tokens": 32, "output_tokens": 2,
                                  "head_calls": 1, "router_calls": 0,
                                  "encoder_calls": 1, "graph_calls": 0,
                                  "energy_joules": 0.0},
                })
        self.save_predictions()

    def save_all(self):
        (self.root / "plan.json").write_bytes(canonical(self.plan))
        (self.root / "queries.json").write_bytes(canonical(self.queries))
        (self.root / "gold.json").write_bytes(canonical(self.gold))

    def save_predictions(self):
        for arm, rows in self.predictions.items():
            (self.pred / f"{arm}.jsonl").write_bytes(
                b"".join(canonical(r) + b"\n" for r in rows))

    def run_audit(self):
        return audit(self.root / "plan.json", self.root / "queries.json",
                     self.root / "gold.json", self.pred)

    def test_freeze_plan_create_only_with_exact_bytes(self):
        draft = self.root / "draft.json"
        draft.write_bytes(canonical(self.plan))
        destination = self.root / "sealed.json"
        sealed = freeze_plan(draft, self.root / "queries.json", self.root / "gold.json", destination)
        self.assertEqual(sealed, digest(destination.read_bytes()))
        with self.assertRaises(FileExistsError):
            freeze_plan(draft, self.root / "queries.json", self.root / "gold.json", destination)

    def test_wrong_query_bytes_cannot_be_frozen(self):
        draft = self.root / "draft.json"
        draft.write_bytes(canonical(self.plan))
        self.queries[0]["question"] = "tampered"
        self.save_all()
        with self.assertRaisesRegex(ValueError, "query bytes"):
            freeze_plan(draft, self.root / "queries.json", self.root / "gold.json",
                        self.root / "sealed.json")

    def test_all_nine_arms_pair_by_exact_query_and_group(self):
        receipt = self.run_audit()
        self.assertEqual(receipt["rows"], 9 * len(self.queries))
        self.assertEqual(len(receipt["predeclared_comparisons"]), 8)
        self.assertEqual(receipt["arm_metrics"]["I"]["strict_task_success"], 1.0)
        self.assertFalse(receipt["scientific_superiority_established"])
        self.assertFalse(receipt["production_activation_allowed"])
        self.assertEqual(receipt["qualification"], "SHADOW_ONLY / DENY_ALL / HOLD_NO_GO")

    def test_missing_arm_row_is_fatal(self):
        self.predictions["H"].pop()
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.run_audit()

    def test_duplicate_arm_query_is_fatal(self):
        self.predictions["B"].append(copy.deepcopy(self.predictions["B"][0]))
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "duplicated"):
            self.run_audit()

    def test_invented_source_is_fatal(self):
        self.predictions["C"][0]["selected_source_ids"] = ["invented-source"]
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "invented evidence"):
            self.run_audit()

    def test_old_or_wrong_plan_is_fatal(self):
        self.predictions["I"][0]["plan_sha256"] = "0" * 64
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "plan_sha256"):
            self.run_audit()

    def test_stale_forget_frontier_is_fatal(self):
        self.predictions["D"][0]["forget_frontier_sha256"] = "0" * 64
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "forget_frontier"):
            self.run_audit()

    def test_wrong_citation_is_not_success_even_for_exact_answer(self):
        self.predictions["I"][0]["selected_source_ids"] = []
        self.save_predictions()
        result = self.run_audit()
        self.assertLess(result["arm_metrics"]["I"]["strict_task_success"], 1.0)
        self.assertFalse(result["scientific_superiority_established"])

    def test_unsupported_wrong_answer_is_not_success(self):
        self.predictions["I"][0]["answer"] = "Not the answer"
        self.save_predictions()
        self.assertLess(self.run_audit()["arm_metrics"]["I"]["strict_task_success"], 1.0)

    def test_unanswerable_accepted_is_not_success(self):
        self.predictions["I"][1].update({"abstained": False, "answer": "fabricated"})
        self.save_predictions()
        self.assertLess(self.run_audit()["arm_metrics"]["I"]["strict_task_success"], 1.0)

    def test_gold_in_serving_payload_is_fatal(self):
        self.queries[0]["expected_answer"] = "A fact"
        self.plan["query_sha256"] = digest(canonical(self.queries))
        self.save_all()
        with self.assertRaisesRegex(ValueError, "strict fields"):
            self.run_audit()

    def test_split_leakage_rejected(self):
        self.roles["calibration"] = ["train-1"]
        self.plan["splits"] = self.roles
        self.save_all()
        with self.assertRaisesRegex(ValueError, "source group crosses"):
            self.run_audit()

    def test_negative_budget_rejected(self):
        self.predictions["E"][0]["resources"]["wall_ms"] = -1.0
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "nonfinite/negative"):
            self.run_audit()

    def test_boolean_resource_rejected(self):
        self.predictions["E"][0]["resources"]["head_calls"] = True
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "Boolean resource"):
            self.run_audit()

    def test_over_budget_rejected(self):
        self.predictions["E"][0]["resources"]["head_calls"] = 9
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "budget overrun"):
            self.run_audit()

    def test_future_harm_is_exposed_without_cherry_picking(self):
        # Make I fail a future group while leaving its entire evaluation untouched.
        record = next(r for r in self.predictions["I"] if r["query_id"] == "future_1-0")
        record["answer"] = "wrong"
        self.save_predictions()
        receipt = self.run_audit()
        self.assertFalse(receipt["future_non_regression_gate"])
        self.assertTrue(any(x["delta"] < 0 for x in receipt["future_holdout_comparisons"]
                            if x["split"] == "future_1"))
        self.assertFalse(receipt["scientific_superiority_established"])

    def test_multi_hop_safety_harm_is_exposed(self):
        record = next(r for r in self.predictions["I"] if r["query_id"] == "evaluation-0")
        record["answer"] = "wrong"
        self.save_predictions()
        receipt = self.run_audit()
        self.assertFalse(receipt["critical_slice_non_regression_gate"])
        self.assertFalse(receipt["diagnostic_statistical_gate"])

    def test_empty_future_window_is_not_promoted(self):
        # The observed test is small and cannot support independent longitudinal claims.
        receipt = self.run_audit()
        self.assertFalse(receipt["diagnostic_statistical_gate"])
        self.assertFalse(receipt["scientific_superiority_established"])
        self.assertLess(receipt["group_counts"]["evaluation"], self.plan["minimum_independent_groups"])

    def test_arm_relabel_or_p_hacking_rejected(self):
        self.plan["comparisons"].reverse()
        self.save_all()
        with self.assertRaisesRegex(ValueError, "comparisons must be frozen"):
            self.run_audit()

    def test_gold_byte_tamper_rejected(self):
        self.gold[0]["acceptable_answers"] = ["tampered"]
        self.save_all()
        with self.assertRaisesRegex(ValueError, "gold bytes"):
            self.run_audit()

    def test_missing_source_snapshot_rejected(self):
        self.predictions["B"][0]["source_snapshot_sha256"] = "0" * 64
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "source_snapshot_sha256"):
            self.run_audit()

    def test_refuses_extra_prediction_metrics(self):
        self.predictions["I"][0]["claimed_success"] = True
        self.save_predictions()
        with self.assertRaisesRegex(ValueError, "strict fields"):
            self.run_audit()


if __name__ == "__main__":
    unittest.main()
