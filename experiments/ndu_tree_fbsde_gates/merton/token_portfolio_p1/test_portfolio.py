"""P1 contract and adversarial tests: synthetic mechanisms, no pretrained LLM."""
from __future__ import annotations

import copy
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction as Q
from pathlib import Path

from portfolio import Invalid, allocate, exact, fit, manifest, public_cases, run, score
from replay import read, review, write_new


def panel():
    m = {
        "schema": "hepta.ndu-merton.token-portfolio-p1.v1",
        "actions": [
            {"name": "direct", "token_ceiling": 0, "latency_ceiling_ms": 0},
            {"name": "reason", "token_ceiling": 4, "latency_ceiling_ms": 3},
            {"name": "verify", "token_ceiling": 2, "latency_ceiling_ms": 1},
        ],
        "token_budget": 8, "latency_budget_ms": 7, "token_tariff": "1/64",
    }
    t = {"schema": "hepta.p1.train.v1", "rows": []}
    for bucket in ("easy", "hard"):
        for group in ("past-A", "past-B"):
            for i in range(2):
                tid = f"{bucket}-{group}-{i}"
                for action in ("direct", "reason", "verify"):
                    success = int(
                        (bucket == "hard" and action == "reason") or
                        (bucket == "hard" and action == "verify" and i == 0) or
                        (bucket == "easy" and action == "direct" and (i == 0 or group == "past-A")) or
                        (bucket == "easy" and action != "direct")
                    )
                    t["rows"].append({"task_id": tid, "bucket": bucket, "group": group,
                                      "action": action, "success": success})
    p = {"schema": "hepta.p1.public.v1", "cases": [
        {"task_id": "future-1", "bucket": "hard", "group": "future-X"},
        {"task_id": "future-2", "bucket": "easy", "group": "future-Y"},
        {"task_id": "future-3", "bucket": "hard", "group": "future-X"},
        {"task_id": "future-4", "bucket": "easy", "group": "future-Y"},
    ]}
    truth = {"schema": "hepta.p1.postseal-truth.v1", "cases": []}
    for i, task in enumerate(p["cases"]):
        truth["cases"].append({"task_id": task["task_id"], "actions": [
            {"action": "direct", "success": int(i % 2 == 1), "actual_incremental_tokens": 0,
             "actual_latency_ms": 0},
            {"action": "reason", "success": 1, "actual_incremental_tokens": 4,
             "actual_latency_ms": 3},
            {"action": "verify", "success": int(i != 0), "actual_incremental_tokens": 2,
             "actual_latency_ms": 1},
        ]})
    return m, t, p, truth


class TokenPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.m, self.t, self.p, self.truth = panel()

    def assert_bad(self, m=None, t=None, p=None, truth=None, sealed=None):
        with self.assertRaises(Invalid):
            if truth is None:
                run(m or self.m, t or self.t, p or self.p)
            else:
                review(m or self.m, t or self.t, p or self.p,
                       sealed if sealed is not None else run(self.m, self.t, self.p), truth)

    def test_complete_seal_and_same_objective_parity(self):
        attempt = run(self.m, self.t, self.p)
        scores = attempt["attempt"]["policies"]
        self.assertEqual(len(scores), 7)
        self.assertEqual(scores[-2]["assignments"], scores[-1]["assignments"])
        self.assertEqual(scores[-2]["estimated_net_gain"], scores[-1]["estimated_net_gain"])
        self.assertTrue(all(s["reserved_tokens"] <= 8 and s["reserved_latency_ms"] <= 7 for s in scores))
        self.assertTrue(all(s["qualification"] == "RESEARCH_ONLY_DENY_ALL" for s in scores))
        self.assertNotIn("success", json.dumps(attempt))
        self.assertNotIn("future-X", json.dumps(attempt))

    def test_exact_knapsack_vs_independent_enumeration(self):
        acts, budget, latency, fee = manifest(self.m)
        cases = public_cases(self.p)
        rates, alpha = fit(self.t, acts, cases)
        dp = allocate(cases, acts, budget, latency, rates, fee, alpha, "ndu_discrete")
        expected = Q(dp["estimated_net_gain"])
        maximum = max(
            (sum((score(c, a, rates, alpha, fee) for c,a in zip(cases, choices)), Q(0))
             for choices in itertools.product(acts, repeat=len(cases))
             if sum(a.token_ceiling for a in choices) <= budget
             and sum(a.latency_ceiling_ms for a in choices) <= latency),
            default=None,
        )
        self.assertEqual(expected, maximum)

    def test_budget_zero_yields_no_purchase(self):
        self.m["token_budget"] = 0
        for row in run(self.m, self.t, self.p)["attempt"]["policies"]:
            self.assertTrue(all(a == "direct" for a in row["assignments"].values()))

    def test_greedy_and_fixed_never_exceed_budgets(self):
        self.m["token_budget"], self.m["latency_budget_ms"] = 4, 3
        a = run(self.m, self.t, self.p)["attempt"]["policies"]
        self.assertTrue(all(row["reserved_tokens"] <= 4 for row in a))
        self.assertTrue(all(row["reserved_latency_ms"] <= 3 for row in a))

    def test_review_recounts_realized_outcomes_no_savings(self):
        sealed = run(self.m, self.t, self.p)
        summary = review(self.m, self.t, self.p, sealed, self.truth)
        self.assertEqual(summary["interpretation"], "RETROSPECTIVE_FULL_TRACE_PAID_NO_ON_POLICY_PHYSICAL_SAVINGS")
        self.assertEqual(summary["full_precomputed_trace_reported_tokens"], 24)
        direct = summary["policy_scores"][0]
        self.assertEqual(direct["counterfactual_selected_tokens"], 0)
        self.assertEqual(direct["correct_tasks"], 2)
        self.assertEqual(summary["policy_scores"][-1]["correct_tasks"], summary["policy_scores"][-2]["correct_tasks"])

    def test_untrusted_public_gold_key_rejected(self):
        self.p["cases"][0]["correct"] = 1
        self.assert_bad()

    def test_untrusted_public_future_action_prediction_rejected(self):
        self.p["cases"][0]["future_predictions"] = [1, 1]
        self.assert_bad()

    def test_duplicated_public_case_rejected(self):
        self.p["cases"][1]["task_id"] = "future-1"
        self.assert_bad()

    def test_train_public_identity_collision_rejected(self):
        self.p["cases"][0]["task_id"] = self.t["rows"][0]["task_id"]
        self.assert_bad()

    def test_train_public_source_group_collision_rejected(self):
        self.p["cases"][0]["group"] = "past-A"
        self.assert_bad()

    def test_missing_train_pair_rejected(self):
        self.t["rows"].pop()
        self.assert_bad()

    def test_train_duplicate_pair_rejected(self):
        self.t["rows"].append(copy.deepcopy(self.t["rows"][0]))
        self.assert_bad()

    def test_unsupported_bucket_rejected(self):
        self.p["cases"][0]["bucket"] = "unknown"
        self.assert_bad()

    def test_unsupported_fewer_than_two_groups_rejected(self):
        for row in self.t["rows"]:
            if row["bucket"] == "hard":
                row["group"] = "past-A"
        self.assert_bad()

    def test_negative_budget_rejected(self):
        self.m["token_budget"] = -1
        self.assert_bad()

    def test_bool_count_rejected(self):
        self.m["token_budget"] = True
        self.assert_bad()

    def test_direct_cost_rejected(self):
        self.m["actions"][0]["token_ceiling"] = 1
        self.assert_bad()

    def test_fee_float_rejected(self):
        self.m["token_tariff"] = 0.01
        self.assert_bad()

    def test_fee_outside_bounds_rejected(self):
        self.m["token_tariff"] = "3/2"
        self.assert_bad()

    def test_nonbinary_train_outcome_rejected(self):
        self.t["rows"][0]["success"] = 2
        self.assert_bad()

    def test_wrong_protocol_rejected(self):
        self.m["schema"] = "legacy"
        self.assert_bad()

    def test_bad_seal_denied(self):
        attempt = run(self.m, self.t, self.p)
        attempt["attempt"]["policies"][0]["reserved_tokens"] = 9
        self.assert_bad(truth=self.truth, sealed=attempt)

    def test_resealed_policy_tamper_denied(self):
        from portfolio import digest
        attempt = run(self.m, self.t, self.p)
        attempt["attempt"]["policies"][0]["reserved_tokens"] = 9
        attempt["seal_sha256"] = digest(attempt["attempt"])
        self.assert_bad(truth=self.truth, sealed=attempt)

    def test_reviewer_rejects_missing_counterfactual_outcome(self):
        self.truth["cases"][0]["actions"].pop()
        self.assert_bad(truth=self.truth)

    def test_reviewer_rejects_excess_real_tokens(self):
        self.truth["cases"][0]["actions"][1]["actual_incremental_tokens"] = 5
        self.assert_bad(truth=self.truth)

    def test_reviewer_rejects_tampered_original_task(self):
        self.truth["cases"][0]["task_id"] = "forged"
        self.assert_bad(truth=self.truth)

    def test_reviewer_rejects_outcome_bool(self):
        self.truth["cases"][0]["actions"][0]["success"] = True
        self.assert_bad(truth=self.truth)

    def test_reviewer_rejects_overlong_physical_latency(self):
        self.truth["cases"][0]["actions"][1]["actual_latency_ms"] = 4
        self.assert_bad(truth=self.truth)

    def test_duplicate_json_keys_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"duplicate.json"
            path.write_text('{"schema":"a","schema":"b"}')
            with self.assertRaises(Invalid):
                read(str(path))

    def test_nonfinite_json_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"nonfinite.json"
            path.write_text('{"x":NaN}')
            with self.assertRaises(Invalid):
                read(str(path))

    def test_create_only_output_rejects_preplant(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d)/"seal.json")
            write_new(path, {"x": 1})
            with self.assertRaises(FileExistsError):
                write_new(path, {"x": 2})

    def test_producer_cli_refuses_truth_path(self):
        proc = subprocess.run([sys.executable, str(Path(__file__).with_name("replay.py")),
                               "producer", "--manifest", "a", "--train", "b", "--public", "c",
                               "--output", "d", "--truth", "truth.json"],
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("must not receive truth", proc.stderr)

    def test_cli_normal_and_optimized_independently_score(self):
        with tempfile.TemporaryDirectory() as d:
            for name, obj in (("manifest",self.m),("train",self.t),("public",self.p),("truth",self.truth)):
                (Path(d)/f"{name}.json").write_text(json.dumps(obj))
            for optim in (False, True):
                prefix = [sys.executable] + (["-O"] if optim else [])
                producer = subprocess.run(prefix + [str(Path(__file__).with_name("replay.py")), "producer",
                    "--manifest",str(Path(d)/"manifest.json"),"--train",str(Path(d)/"train.json"),
                    "--public",str(Path(d)/"public.json"),"--output",str(Path(d)/f"attempt-{optim}.json")],
                    capture_output=True, text=True)
                self.assertEqual(producer.returncode, 0, producer.stderr)
                reviewer = subprocess.run(prefix + [str(Path(__file__).with_name("replay.py")), "review",
                    "--manifest",str(Path(d)/"manifest.json"),"--train",str(Path(d)/"train.json"),
                    "--public",str(Path(d)/"public.json"),"--sealed",str(Path(d)/f"attempt-{optim}.json"),
                    "--truth",str(Path(d)/"truth.json"),"--output",str(Path(d)/f"review-{optim}.json")],
                    capture_output=True, text=True)
                self.assertEqual(reviewer.returncode, 0, reviewer.stderr)
            x, y = (read(str(Path(d)/f"review-{o}.json")) for o in (False,True))
            self.assertEqual(x,y)


if __name__ == "__main__":
    unittest.main()
