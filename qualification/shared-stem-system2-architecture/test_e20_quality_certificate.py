"""Evidence-bound numerical and fail-closed E20 contract tests (no new weights)."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from e14_multirc_route import read_prelabel
from e20_quality_certificate import (analyze, binary_brier_bound, sigmoid,
                                     physical_batch_measure, produce)
from e20_independent_quality_review import independently_compute, review

ARCHIVE = os.environ.get("HEPTA_E20_ORIGINAL_MULTIRC_ARCHIVE", "")


class QualityOriginalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ARCHIVE:
            raise RuntimeError("E20 genuine original ZIP is REQUIRED, never skip")
        cls.obs=read_prelabel(ARCHIVE)
        cls.report=analyze(cls.obs,meter_repeats=6)

    def test_original_real_33_candidates_are_pinned(self):
        x=self.report
        self.assertEqual((x["original_passages"],x["original_questions"],x["original_candidates"]),(4,8,33))
        self.assertEqual(sum(x["rows"][i]["candidate_count"] for i in range(8)),33)
        self.assertFalse(x["human_labels_seen_by_producer"])

    def test_every_arm_precision_preserves_all_33_hard_labels(self):
        for arm,records in self.report["summary"].items():
            for name,v in records.items():
                with self.subTest(arm=arm,precision=name):
                    self.assertEqual(v["hard_decision_changes"],0)
                    self.assertIs(v["exact_archive_accuracy_parity_for_any_binary_labels"],True)
                    self.assertEqual(v["candidate_count"],33)

    def test_rounding_detail_and_accuracy_are_distinct_claims(self):
        cond=self.report["summary"]["conditioned"]
        self.assertGreater(cond["bf16_two_logits_then_sub"]["mean_absolute_probability_shift"],0)
        self.assertEqual(cond["bf16_two_logits_then_sub"]["hard_decision_changes"],0)
        self.assertTrue(self.report["numerical_precision_only_no_semantic_reasoning_claim"])

    def test_zero_class_tie_is_not_positive(self):
        # Actual archived output does not have changed ties; adversarial tiny
        # positive margin that rounds to BF16 tie MUST change class1 -> class0.
        self.assertTrue(1.0+1e-5>1.0)
        from e19_precision_pack import encode_group
        vals=encode_group(((1.0,1.0+1e-5),(1.0,1.0+1e-5)))
        raw=vals["original_fp32"][0]
        collapsed=vals["bf16_two_logits_then_sub"][0]
        self.assertGreater(raw,0)
        self.assertEqual(collapsed,0)
        self.assertNotEqual(raw>0,collapsed>0)
        self.assertNotEqual(raw>=0,collapsed>0)

    def test_binary_brier_envelope_handles_both_possible_labels(self):
        for p,q in ((0.,0.),(.51,.5),(.7,.1),(0.,1.),(.1,.3)):
            worst=binary_brier_bound(float(p),float(q))
            for truth in (0,1):
                b0=2*(p-truth)**2;b1=2*(q-truth)**2
                self.assertLessEqual(abs(b1-b0),worst+1e-15)

    def test_invalid_predictive_probabilities_fail(self):
        for a,b in ((float('nan'),.4),(-.1,.3),(.2,1.3),(False,.2)):
            with self.subTest(a=a,b=b),self.assertRaises(ValueError):
                binary_brier_bound(a,b)
        for x in (float('inf'),"0",True,17.):
            with self.subTest(x=x),self.assertRaises(ValueError):
                sigmoid(x)

    def test_source_refuses_missing_models_and_source_hash(self):
        for mutate in (
            lambda o:o.update(observation_id="0"*64),
            lambda o:o["predictions"].pop("conditioned"),
            lambda o:o["rows"].pop(),
        ):
            bad=deepcopy(self.obs)
            mutate(bad)
            with self.assertRaises((ValueError,KeyError,TypeError)):
                analyze(bad,meter_repeats=4)

    def test_source_guard_rejects_invalid_meter_bounds(self):
        for r in (0,201,True,3):
            with self.assertRaises(ValueError):physical_batch_measure(self.obs,r)

    def test_arithmetic_cost_work_is_paid_and_exclusions_explicit(self):
        result=self.report["self_observed_cpu_arithmetic_only"]
        self.assertEqual(set(result),{"fp32_direct","bf16_direct","bf16_centered"})
        for name,v in result.items():
            self.assertEqual(len(v["actual_cpu_ns"]),6)
            self.assertEqual(v["work_per_batch"],132)
            self.assertTrue(all(x>0 for x in v["actual_cpu_ns"]))
        self.assertFalse(self.report["complete_model_forward_training_caching_network_storage_energy_verifier_cost_measured"])

    def test_two_separate_algorithms_agree_original_real_model(self):
        rows,summary=independently_compute(self.obs)
        self.assertEqual(len(rows),len(self.report["rows"]))
        for arm in self.report["summary"]:
            for profile in self.report["profiles"]:
                a=self.report["summary"][arm][profile]
                b=summary[arm][profile]
                self.assertEqual(a["hard_decision_changes"],b["hard_decision_changes"])
                self.assertAlmostEqual(a["max_absolute_probability_shift"],b["max_absolute_probability_shift"],delta=2e-14)
                self.assertAlmostEqual(a["human_label_independent_brier_delta_upper_bound"],b["brier_delta_bound"],delta=2e-14)

    def test_producer_and_independent_original_human_review(self):
        with tempfile.TemporaryDirectory() as temp:
            blind=Path(temp)/"blind.json"; score=Path(temp)/"score.json"
            sha=produce(ARCHIVE,str(blind))
            review_sha=review(str(blind),sha,ARCHIVE,str(score))
            self.assertEqual(review_sha,sha256(score.read_bytes()).hexdigest())
            report=json.loads(score.read_text())
            self.assertTrue(report["source_recomputed_hard_accuracy_parity"])
            self.assertFalse(report["prospective_task_improvement"])
            self.assertEqual(report["historical_human_metric_envelopes"]["conditioned"]["bf16_two_logits_then_sub"]
                             ["reconstructed_accuracy_correct_if_no_hard_changes"],16)
            self.assertEqual(report["historical_human_metric_envelopes"]["no_query"]["original_fp32"]
                             ["reconstructed_accuracy_correct_if_no_hard_changes"],19)

    def test_seal_binding_rejects_mutated_blind(self):
        with tempfile.TemporaryDirectory() as temp:
            blind=Path(temp)/"blind.json";out=Path(temp)/"score.json"
            sha=produce(ARCHIVE,str(blind))
            data=blind.read_text().replace('"DENY_ALL"','"ALLOW_ALL"')
            blind.write_text(data)
            with self.assertRaises(ValueError):review(str(blind),sha,ARCHIVE,str(out))

    def test_rehashed_forgery_still_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            blind=Path(temp)/"blind.json";out=Path(temp)/"score.json"
            produce(ARCHIVE,str(blind))
            data=json.loads(blind.read_text())
            data["summary"]["conditioned"]["bf16_two_logits_then_sub"]["hard_decision_changes"]=1
            blind.write_text(json.dumps(data))
            forged=sha256(blind.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):review(str(blind),forged,ARCHIVE,str(out))

    def test_rehashed_cost_padding_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            blind=Path(temp)/"blind.json";out=Path(temp)/"score.json"
            produce(ARCHIVE,str(blind))
            data=json.loads(blind.read_text())
            data["self_observed_cpu_arithmetic_only"]["bf16_centered"]["p50_cpu_ns"] += 40_000
            blind.write_text(json.dumps(data))
            with self.assertRaises(ValueError):review(str(blind),sha256(blind.read_bytes()).hexdigest(),ARCHIVE,str(out))

    def test_unknown_authority_and_model_claim_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            blind=Path(temp)/"blind.json";out=Path(temp)/"score.json"
            produce(ARCHIVE,str(blind))
            for k,value in (("production_accepted",True),("new_pretrained_forward_count",True),
                            ("model_weights_loaded",True),("unknown_owner",123)):
                data=json.loads(blind.read_text());data[k]=value
                changed=Path(temp)/f"{k}.json";changed.write_text(json.dumps(data))
                with self.subTest(k=k),self.assertRaises(ValueError):
                    review(str(changed),sha256(changed.read_bytes()).hexdigest(),ARCHIVE,str(out))

    def test_blind_source_does_not_open_scored_members(self):
        # Pinned blind reader only opens archived candidate audit and its seal.
        import inspect
        import e14_multirc_route as ancestor
        reader=inspect.getsource(ancestor.read_prelabel)
        self.assertIn("obs_raw = z.read(MEMBER)",reader)
        self.assertNotIn("z.read(SCORE_PATH)",reader)
        self.assertFalse(self.report["human_labels_seen_by_producer"])


if __name__=="__main__":unittest.main()
