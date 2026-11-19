"""E19 adversarial ORIGINAL pretrained Reader signal-preservation tests.

No synthetic stand-in for original archive or human truth, no promotion.
"""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from e14_multirc_route import ARMS, read_prelabel
from e19_precision_pack import (SCHEMA, PROFILES, analyze, encode_group, fp32,
                                group_source, margins_for, metrics, produce, quantize)
from e19_independent_review import (independent_cast,
                                    independently_build, equal_with_types, review)
from e19_torch_cast import actual_torch_casts, run as run_physical


class OriginalRealPretrainedPrecisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=os.environ.get("HEPTA_E19_ORIGINAL_ARCHIVE",
                                  "/mnt/data/hepta-artifact-11946621518.zip")
        cls.original=read_prelabel(cls.source)
        cls.blind=analyze(cls.original)

    def test_original_complete_real_source_not_toy(self):
        self.assertEqual((len(self.blind["question_rows"]),self.blind["original_candidates"]),(8,33))
        self.assertEqual(len(set(q["source_group"] for q in self.blind["question_rows"])),4)
        self.assertEqual(sum(q["candidate_count"] for q in self.blind["question_rows"]),33)
        self.assertEqual(self.blind["schema"],SCHEMA)
        self.assertEqual(self.blind["authority"],"DENY_ALL")
        self.assertFalse(self.blind["production_accepted"])

    def test_bf16_ordering_matters_for_real_conditioned_source(self):
        expected={
            "original_fp32":(4,36,0),
            "bf16_two_logits_then_sub":(8,55,19),
            "bf16_margin_after_sub":(8,55,19),
            "bf16_question_centered_with_fp32_anchor":(4,36,0),
        }
        for profile,(invariant,pairs,new_ties) in expected.items():
            with self.subTest(profile=profile):
                report=self.blind["summary"]["conditioned"][profile]
                self.assertEqual((report["candidate_invariant_questions"],report["equal_margin_pairs"],
                                  report["new_false_ties_relative_to_fp32"]),
                                 (invariant,pairs,new_ties))

    def test_cannot_erase_true_source_invariants(self):
        self.assertEqual(self.blind["summary"]["no_query"]["original_fp32"]["candidate_invariant_questions"],8)
        self.assertEqual(self.blind["summary"]["no_query"]["bf16_question_centered_with_fp32_anchor"]
                         ["candidate_invariant_questions"],8)
        self.assertEqual(self.blind["summary"]["conditioned"]["original_fp32"]
                         ["candidate_invariant_questions"],4)

    def test_four_real_readers_and_all_precision_arms(self):
        self.assertEqual(set(self.blind["summary"]),set(ARMS))
        for name in ARMS:
            self.assertEqual(set(self.blind["summary"][name]),set(PROFILES))
            for p in PROFILES:
                self.assertEqual(sum(q["arms"][name][p]["candidate_pairs"] for q in
                                     self.blind["question_rows"]),55)

    def test_independent_fraction_exponent_math_exact_replay(self):
        independent=independently_build(self.original)
        equal_with_types(self.blind,independent)
        self.assertEqual(self.blind["summary"]["conditioned"]["bf16_question_centered_with_fp32_anchor"]
                         ["pair_order_reversals_relative_to_fp32"],0)

    def test_all_264_original_logit_values_and_casts_have_second_oracle(self):
        count=0
        for _, indices in group_source(self.original):
            for arm in ARMS:
                for pair in margins_for(self.original,arm,indices):
                    for v in pair:
                        for mode in ("fp32","fp16","bf16"):
                            self.assertEqual(quantize(v,mode),independent_cast(v,mode))
                            count+=1
        self.assertEqual(count,33*4*2*3)

    def test_physical_pytorch_cpu_bf16_fp16_cast(self):
        receipt=actual_torch_casts(self.original)
        self.assertEqual(receipt["numeric_roundtrip_comparisons"],792)
        self.assertEqual(receipt["numeric_mismatches"],0)
        self.assertEqual(receipt["device"],"cpu")
        self.assertTrue(receipt["physical_fp32_to_bf16_fp16_tensor_casts_executed"])
        self.assertTrue(receipt["no_pretrained_encoder_or_reader_forward"])

    def test_storage_geometry_not_physical_service_claim(self):
        self.assertEqual(self.blind["original_fp32_pair_weight_bytes_only"],264)
        self.assertEqual(self.blind["bf16_two_logits_storage_bytes_only"],132)
        self.assertEqual(self.blind["bf16_margin_only_storage_bytes_only"],66)
        self.assertEqual(self.blind["centered_bf16_margin_plus_fp32_question_anchor_storage_bytes_only"],98)
        self.assertTrue(self.blind["additional_FP32_group_aggregation_cost_unmeasured"])
        self.assertFalse(self.blind["real_model_serving_latency_measured"])

    def test_standard_ieee_even_ties(self):
        self.assertEqual(quantize(1+2**-8,"bf16"),1)
        self.assertEqual(quantize(1+3*2**-8,"bf16"),1+2**-6)
        self.assertEqual(quantize(-1-2**-8,"bf16"),-1)
        self.assertEqual(quantize(1+2**-11,"fp16"),1)
        self.assertEqual(quantize(1+3*2**-11,"fp16"),1+2**-9)

    def test_invalid_typed_scalar_rejected(self):
        for v in [True,False,"0.1",None,float("nan"),float("inf"),20]:
            with self.subTest(v=v),self.assertRaises(ValueError):fp32(v)

    def test_invalid_precision_profile(self):
        for profile in ("FP16","int8", "bfloat16", "bf16_with_permission"):
            with self.subTest(profile=profile),self.assertRaises(ValueError):quantize(0.5,profile)

    def test_incomplete_or_wrong_question_group(self):
        with self.assertRaises(ValueError):encode_group(((1.0,2.0),))
        with self.assertRaises(ValueError):encode_group(((1.0,2.0),)*9)
        bad=copy.deepcopy(self.original)
        bad["rows"][1]["task_id"]=bad["rows"][0]["task_id"]
        with self.assertRaises(ValueError):group_source(bad)

    def test_modified_prediction_source_rejected(self):
        bad=copy.deepcopy(self.original)
        bad["predictions"]["conditioned"][2]["logits"][0]+=0.1
        with self.assertRaises(ValueError):margins_for(bad,"conditioned",group_source(bad)[0][1])
        # Replay of a mismatched checksum cannot fall back to a new inference.
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"fake.zip";p.write_bytes(Path(self.source).read_bytes()+b"forged")
            with self.assertRaises(ValueError):read_prelabel(str(p))

    def test_generated_false_tie_and_reverse_control(self):
        v=metrics((0.0,0.01,0.02),(0.0,0.0,-0.01))
        self.assertEqual(v["new_false_ties_relative_to_fp32"],1)
        self.assertEqual(v["pair_order_reversals_relative_to_fp32"],2)

    def test_independent_reject_forged_summary(self):
        altered=copy.deepcopy(self.blind)
        altered["summary"]["conditioned"]["bf16_question_centered_with_fp32_anchor"]\
            ["candidate_invariant_questions"]=0
        with self.assertRaises(ValueError):equal_with_types(altered,independently_build(self.original))

    def test_independent_reject_forged_question_measure(self):
        altered=copy.deepcopy(self.blind)
        altered["question_rows"][0]["arms"]["conditioned"]["bf16_margin_after_sub"]\
            ["maximum_candidate_margin_span"]+=0.25
        with self.assertRaises(ValueError):equal_with_types(altered,independently_build(self.original))

    def test_independent_reject_authority_and_boolean_retyping(self):
        for path,val in (("authority","PRODUCTION"),("production_accepted",1),
                         ("no_new_pretrained_forwards",1),("original_human_labels_opened_before_blind_seal",1),
                         ("model_selected",True)):
            with self.subTest(path=path):
                altered=copy.deepcopy(self.blind);altered[path]=val
                with self.assertRaises(ValueError):equal_with_types(altered,independently_build(self.original))

    def test_independent_reject_unknown_fields_even_if_benign(self):
        altered=copy.deepcopy(self.blind);altered["authorized_by_model"]=False
        with self.assertRaises(ValueError):equal_with_types(altered,independently_build(self.original))

    def test_independent_reject_changed_origin_and_storage_claim(self):
        for key,value in (("archive_sha256","0"*64),
                          ("original_pretrained_observation_id","1"*64),
                          ("centered_bf16_margin_plus_fp32_question_anchor_storage_bytes_only",66)):
            with self.subTest(key=key):
                bad=copy.deepcopy(self.blind);bad[key]=value
                with self.assertRaises(ValueError):equal_with_types(bad,independently_build(self.original))

    def test_original_human_score_only_opened_after_seal(self):
        with TemporaryDirectory() as tmp:
            blind=Path(tmp)/"blind.json";out=Path(tmp)/"review.json"
            digest=produce(self.source,str(blind))
            self.assertFalse(out.exists())
            score_sha=review(self.source,str(blind),digest,str(out))
            self.assertEqual(score_sha,sha256(out.read_bytes()).hexdigest())
            human=json.loads(out.read_text())
            self.assertEqual(human["historical_human_questions_with_mixed_labels"],8)
            self.assertFalse(human["actual_online_latency_or_watt_benefit"])
            self.assertFalse(human["model_selected"])

    def test_create_only_never_overwrites_seals(self):
        with TemporaryDirectory() as tmp:
            a=Path(tmp)/"blind.json";b=Path(tmp)/"score.json"
            digest=produce(self.source,str(a))
            with self.assertRaises(FileExistsError):produce(self.source,str(a))
            review(self.source,str(a),digest,str(b))
            with self.assertRaises(FileExistsError):review(self.source,str(a),digest,str(b))

    def test_sealed_sha_rejects_semantically_same_changed_bytes(self):
        with TemporaryDirectory() as tmp:
            a=Path(tmp)/"blind.json";b=Path(tmp)/"score.json"
            digest=produce(self.source,str(a))
            a.write_bytes(a.read_bytes()+b"\n")
            with self.assertRaises(ValueError):review(self.source,str(a),digest,str(b))

    def test_independent_reject_changed_outer_blob_even_if_rehashed(self):
        with TemporaryDirectory() as tmp:
            a=Path(tmp)/"blind.json";b=Path(tmp)/"score.json"
            produce(self.source,str(a))
            broken=json.loads(a.read_text());broken["online_inference_gain_established"]=True
            data=json.dumps(broken,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n"
            a.write_bytes(data)
            with self.assertRaises(ValueError):review(self.source,str(a),sha256(data).hexdigest(),str(b))

    def test_independent_reject_incomplete_candidate_original(self):
        altered=copy.deepcopy(self.original);altered["rows"].pop()
        with self.assertRaises(ValueError):independently_build(altered)

    def test_torch_receipt_create_only_and_non_authorizing(self):
        with TemporaryDirectory() as tmp:
            output=Path(tmp)/"physical.json"
            checksum=run_physical(self.source,str(output))
            self.assertEqual(checksum,sha256(output.read_bytes()).hexdigest())
            data=json.loads(output.read_text())
            self.assertFalse(data["production_accepted"])
            self.assertFalse(data["actual_BF16_model_quality_or_serving_latency_measured"])
            with self.assertRaises(FileExistsError):run_physical(self.source,str(output))


if __name__=="__main__": unittest.main()
