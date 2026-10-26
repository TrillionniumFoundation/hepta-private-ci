"""Source-paired DEV means, strict complete census and immutable entry margins."""

import copy
from itertools import product
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from remaining_audit_core_v8 import METHODS, read
from remaining_dev_statistics_v8 import AXES, CANDIDATE, summarize, validate_entry
from score_remaining_v8 import metrics


def synthetic():
    rows, arrays, parity = [], {}, []
    for v, t, h, s in product(*AXES):
        fit, seed_delta = f"{v}-{t}-seed{s}-{h}", {7: -.02, 17: -.01, 29: 0.}[s]
        warm_key = fit+"__warm"
        arrays[warm_key] = np.ones(512)
        parity.append({"fit": fit, "complete": True, "passed": True,
            "max_states_difference": 0., "max_actions_difference": 0., "max_old_losses_difference": 0.})
        for method in METHODS:
            effect = method in (CANDIDATE, "full_adjoint_remaining")
            keys = {role+"_nll": fit+"__"+method+"__"+role for role in ("future", "old")}
            arrays[keys["future_nll"]] = np.full(512, 1.+(seed_delta if effect else 0.))
            arrays[keys["old_nll"]] = np.full(512, .97 if effect else 1.)
            rows.append({"version": v, "task": t, "head": h, "seed": s, "fit": fit, "method": method,
                "available": True, "complete32": True, "status": "completed", "completed_steps": 32,
                "actual_errors": [], "cpu_ns": 200 if effect else 100, "selection_sources_sha256": "f"*64,
                "array_keys": keys, "warmup_old_nll_key": warm_key,
                **{role: {"nll": float(arrays[keys[role+"_nll"]].mean()), "accuracy": .5} for role in ("future", "old")}})
    return rows, arrays, parity


class RemainingStatisticsTests(unittest.TestCase):
    def test_same_source_three_seed_pairing_and_all_entry_counts(self):
        rows, arrays, parity = synthetic()
        result = summarize(rows, arrays, parity)
        self.assertEqual(result["counts"], {"complete32_slots": 96, "actual_error_slots": 0,
            "future_dev_margin_passes": 16, "old_dev_margin_passes": 8, "cost_group_passes": 8,
            "full_field_parity_passed": True})
        self.assertTrue(result["confirmation_entry_passed"])
        self.assertFalse(result["scientific_acceptance"])
        self.assertAlmostEqual(result["groups"][0]["future"][0]["mean_difference"], -.01)
        self.assertEqual(result["groups"][0]["future"][0]["sources"], 512)
        self.assertAlmostEqual(result["groups"][0]["future"][0]["paired_seed_sample_sd"], .01)
        self.assertEqual(result["groups"][0]["candidate_h1_cpu_ratio"], 2.)

    def test_missing_mispaired_or_stopped_policy_never_becomes_a32_step_success(self):
        rows, arrays, parity = synthetic()
        with self.assertRaises(ValueError):
            summarize(rows[:-1], arrays, parity)
        wrong = copy.deepcopy(rows)
        wrong[0]["selection_sources_sha256"] = "e"*64
        with self.assertRaises(ValueError):
            summarize(wrong, arrays, parity)
        stopped = next(r for r in rows if r["method"] == CANDIDATE)
        stopped.update(complete32=False, status="not_executed_rejected", completed_steps=31)
        arrays[stopped["array_keys"]["future_nll"]] = np.zeros(512)
        result = summarize(rows, arrays, parity)
        self.assertFalse(result["confirmation_entry_passed"])
        self.assertEqual(result["counts"]["complete32_slots"], 95)
        self.assertFalse(result["groups"][0]["future"][0]["available32"])
        self.assertIsNone(result["groups"][0]["candidate_h1_cpu_ratio"])

    def test_fixed_rule_rejects_old_execution_or_relaxed_margin_and_metrics_use_actual_labels(self):
        code = Path(__file__).resolve().parents[1]/"hepta-repo-v8/qa/stem-bakeoff"
        rule = read(code/"cell_field_remaining_compressed_confirmation_entry_v8.json")
        report = {"protocol_sha256": rule["control_protocol_sha256"], "source_sha256": rule["control_source_sha256"],
            "source_commit": rule["control_execution_commit"]}
        validate_entry(rule, report)
        wrong = copy.deepcopy(rule)
        wrong["control_source_sha256"] = "0"*64
        with self.assertRaises(ValueError):
            validate_entry(wrong, report)
        wrong = copy.deepcopy(rule)
        wrong["development_plausibility"]["future_loss_candidate_minus_each_comparator"]["mean_upper_bound"] = -.001
        with self.assertRaises(ValueError):
            validate_entry(wrong, report)
        labels = np.arange(512)%4
        probability = np.full((512, 4), .1)
        probability[np.arange(512), labels] = .7
        state = SimpleNamespace(head=SimpleNamespace(predict_proba=lambda x: probability))
        measured, nll, correct = metrics(state, (np.zeros((512, 8)), labels))
        self.assertAlmostEqual(measured["nll"], -np.log(.7))
        self.assertTrue(correct.all())
        changed, _, _ = metrics(state, (np.zeros((512, 8)), (labels+1)%4))
        self.assertAlmostEqual(changed["nll"], -np.log(.1))
        self.assertEqual(changed["accuracy"], 0.)


if __name__ == "__main__":
    unittest.main()
