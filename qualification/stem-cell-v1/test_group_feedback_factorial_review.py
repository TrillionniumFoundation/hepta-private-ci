"""Source-only fault injection for four-armed cross-campaign audit.

The real reviewer calls the full original independent replay first. These
self-contained synthetic fixtures test cross-run validation, NOT model quality.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from group_feedback_factorial_review import MATRIX, COMPARE_ARMS, review_factorial
from group_attention_campaign_review import COHORTS


def sample_result():
    return dict(passed=True, authority="DENY_ALL",
                future_task_efficacy_proved=False,
                real_host_execution_independently_attested=False)


def fixture(root):
    roots = {}
    shared = dict(seed=41, training_profile="sgd_v1", steps=120,
                  public_cases={"train": [dict(case_id="train/1", source_group="s1")]},
                  source_sha256={"frozen": "a"*64},
                  model="same_original_granite97")
    heldout = {name:[True,False] for name in MATRIX}
    heldout["legacy_no_verifier"] = [False,True]
    heldout["guarded_oracle"] = [True,True]
    heldout["guarded_no_verifier"] = [False,False]
    for mode, (guard, feedback) in MATRIX.items():
        directory = root / mode
        directory.mkdir()
        roots[mode] = directory
        p = dict(shared, terminal_guard=guard,
                 training_feedback_policy=feedback)
        receipts = {}
        for arm in ("static","wide","core","attention"):
            oracle = feedback == "legacy_oracle_v1" and arm in ("core","attention")
            receipts[arm] = dict(sample_and_depth_sha256="f"*64,
                                 training_feedback_policy=feedback,
                                 training_verifier_oracle_enabled=oracle,
                                 training_feedback_calls=20 if oracle else 0,
                                 terminal_eligible_step_examples=15 if guard else 0,
                                 terminal_suppressed_step_examples=8 if guard else 0,
                                 optimizer="SGD_without_momentum", cpu_ns=100)
        report = dict(authority="DENY_ALL",production_authorized=False,
                      natural_future_win_established=False,
                      equal_actual_training_work=False,
                      genuine_pretrained_encoder_executed=True,
                      actual_lifecycle_cpu_ns=1000,
                      initial_core_sha256="e"*64,training=receipts,
                      critic_cost={"cpu_ns":80})
        teacher = dict(slot_assignments=[{"case_id":"train/1","slots":[0,1]}],
                       operation_mask_sha256="b"*64,
                       feature_hashes_sha256="c"*64,
                       token_id_retokenized_sha256="d"*64,
                       token_id_forward_witness_sha256="d"*64,
                       source_groups_sha256="e"*64,cpu_ns=40)
        encoder = dict(model_material=dict(model_id="granite97",
                        revision="835ad14087e140460703cf0fae09f97d469d65c2"),
                       actual_forward_calls=12, logical_requests=12,
                       feature_cache_canonical_bytes=12345, cpu_ns=200)
        rows = [dict(cohort=cohort,arm=arm,case_id=f"{cohort}/{i}",
                     source_group=f"source/{cohort}/{i}",
                     feature_sha256=(str(i+1)*64),
                     success=heldout[mode][i],cpu_ns=100,
                     steps=1,verifier_calls=0)
                for cohort in COHORTS for arm in COMPARE_ARMS for i in range(2)]
        for name, obj in (("protocol",p),("report",report),("teacher",teacher),
                          ("encoder",encoder),("observations",rows)):
            (directory / (name+".json")).write_text(
                json.dumps(obj, sort_keys=True), encoding="utf-8")
    return roots


class FeedbackFactorialTests(unittest.TestCase):
    def run_review(self, roots, successful=True):
        with patch("group_feedback_factorial_review.review_single",
                   return_value=sample_result() if successful else {"passed":False}):
            return review_factorial(roots)

    @staticmethod
    def edit(roots, arm, filename, mutator):
        file = roots[arm] / (filename+".json")
        value = json.loads(file.read_text())
        mutator(value)
        file.write_text(json.dumps(value), encoding="utf-8")

    def test_four_policies_and_paired_rescue_harm(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots=fixture(Path(tmp))
            result=self.run_review(roots)
            self.assertTrue(result["passed"])
            self.assertFalse(result["independently_future_tested"])
            self.assertFalse(result["equal_total_compute_demonstrated"])
            test=result["descriptive_paired"]["test"]["attention"]
            self.assertEqual((test["guarded_oracle"]["rescued"],
                              test["guarded_oracle"]["harmed"]),(1,0))
            self.assertEqual((test["legacy_no_verifier"]["rescued"],
                              test["legacy_no_verifier"]["harmed"]),(1,1))
            self.assertEqual((test["guarded_no_verifier"]["rescued"],
                              test["guarded_no_verifier"]["harmed"]),(0,1))
            self.assertEqual(result["costs"]["guarded_no_verifier"]["oracle_feedback_calls"],0)

    def test_require_four_distinct_policy_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots=fixture(Path(tmp))
            with self.assertRaises(ValueError):
                self.run_review({k:v for k,v in roots.items() if k!="guarded_oracle"})
            roots["guarded_oracle"]=roots["legacy_oracle"]
            with self.assertRaises(ValueError):
                self.run_review(roots)

    def test_reject_false_independent_campaign_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots=fixture(Path(tmp))
            with self.assertRaisesRegex(ValueError,"single campaign"):
                self.run_review(roots,False)

    def test_reject_four_policy_label_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots=fixture(Path(tmp))
            self.edit(roots,"guarded_no_verifier","protocol",
                      lambda d:d.update(training_feedback_policy="legacy_oracle_v1"))
            with self.assertRaisesRegex(ValueError,"factorial arm"):
                self.run_review(roots)

    def test_reject_source_model_and_training_sampler_drift(self):
        for filename,mutator in (
            ("protocol",lambda d:d.update(seed=44)),
            ("encoder",lambda d:d.update(actual_forward_calls=13)),
            ("teacher",lambda d:d.update(operation_mask_sha256="f"*64)),
            ("report",lambda d:d.update(initial_core_sha256="a"*64)),
            ("report",lambda d:d["training"]["attention"].update(
                sample_and_depth_sha256="z"*64)),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                roots=fixture(Path(tmp))
                self.edit(roots,"legacy_no_verifier",filename,mutator)
                with self.subTest(filename=filename),self.assertRaises(ValueError):
                    self.run_review(roots)

    def test_reject_changed_heldout_features_and_incomplete_cases(self):
        for mutator in (
            lambda d:d[0].update(feature_sha256="x"*64),
            lambda d:d.pop(),
            lambda d:d[0].update(source_group="forged"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                roots=fixture(Path(tmp))
                self.edit(roots,"guarded_oracle","observations",mutator)
                with self.subTest(mutation=str(mutator)),self.assertRaises(ValueError):
                    self.run_review(roots)

    def test_reject_oracle_policy_drift_and_no_pretrained_claim(self):
        for filename,mutator in (
            ("report",lambda d:d["training"]["core"].update(
                training_verifier_oracle_enabled=True)),
            ("report",lambda d:d.update(genuine_pretrained_encoder_executed=False)),
            ("report",lambda d:d.update(actual_lifecycle_cpu_ns=0)),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                roots=fixture(Path(tmp))
                self.edit(roots,"guarded_no_verifier",filename,mutator)
                with self.subTest(filename=filename),self.assertRaises(ValueError):
                    self.run_review(roots)


if __name__ == "__main__":
    unittest.main()
