"""Adversarial V24 source contracts and separate immutable original archive tests."""
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import v24_multimodal_causal_bounds as v


def fixture():
    """Conspicuously SYNTHETIC 64-case fixture; no real task/model output."""
    cases=[]
    for i in range(64):
        cases.append({"id":f"{i+1:064x}","group":f"{i+1001:064x}","source_input_sha256":f"{i+2001:064x}",
                      "split":"test","arms":{a:[0.4,0.3,0.2,0.1] for a in v.ARMS}})
    pred={"schema":"hepta.e3-granite-dinov2-scienceqa.v1.sealed-predictions",
          "source_sha256":v.SOURCE_SHA256,"arms":sorted(v.ARMS),"predictions":cases,
          "fit_labels_sha256":"a"*64,"fit":{"calibration_selected_weight":0.0,"cell_optimizer_updates":80},
          "production_accepted":False,"same_source_public_release_not_future":True,"held_labels_visible_to_inference":False}
    review={"schema":"hepta.e3-granite-dinov2-scienceqa.v1.independent-heldout-review",
            "source_sha256":v.SOURCE_SHA256,"sealed_predictions_sha256":v.PRED_SHA256,"holdout_targets_sha256":"b"*64,
            "authority":"DENY_ALL","visual_necessity_ground_truth_adjudicated":False,
            "external_ground_truth_independent_owner":False,"production_accepted":False,
            "stem_winner":None,"statistical_selection_authorized":False,
            "original_heldout_cases":64,
            "arms":{a:{"cases":64,"correct":0,"accuracy":0.0} for a in v.ARMS},
            "paired_vs_text_only":{a:{"rescued_errors_vs_text":0,"new_errors_vs_text":0,"discordant_cases":0,
                                       "mcnemar_unadjusted_exact_p":1.0} for a in v.PAIR_ARMS}}
    seals={"source_sha256":v.SOURCE_SHA256,"fit_labels_sha256":"a"*64,"private_test_labels_sha256":"b"*64}
    return pred, review, seals


class SourceOnly(unittest.TestCase):
    def test_fixture_denial(self):
        d=v.analyze(*fixture())
        self.assertEqual(d["decision"],"HOLD_LABELS_AND_CAUSAL_NECESSITY_UNOBSERVED")
        self.assertEqual(d["text_margin_conditional_image_route"]["conditional_image_calls_planned"],0)
        self.assertFalse(d["production_authorized"])

    def altered(self, mutate):
        payload=list(copy.deepcopy(fixture()))
        mutate(*payload)
        with self.assertRaises((v.Invalid,ValueError,TypeError,KeyError)):
            v.analyze(*payload)

    def test_case_duplicates(self):
        self.altered(lambda p,r,s:p['predictions'][1].__setitem__('id',p['predictions'][0]['id']))

    def test_source_identity_rejected(self):
        self.altered(lambda p,r,s:p.__setitem__('source_sha256','e'*64))

    def test_label_seal_rejected(self):
        self.altered(lambda p,r,s:s.__setitem__('private_test_labels_sha256','c'*64))

    def test_wrong_split_rejected(self):
        self.altered(lambda p,r,s:p['predictions'][0].__setitem__('split','train'))

    def test_missing_case_rejected(self):
        self.altered(lambda p,r,s:p['predictions'].pop())

    def test_missing_arm_rejected(self):
        self.altered(lambda p,r,s:p['predictions'][0]['arms'].pop('bridge_image_only'))

    def test_fake_arm_rejected(self):
        self.altered(lambda p,r,s:p['predictions'][0]['arms'].__setitem__('whisper_fake',[0.4,0.3,0.2,0.1]))

    def test_nonfinite_rejected(self):
        self.altered(lambda p,r,s:p['predictions'][0]['arms']['bridge_image_only'].__setitem__(0,float('nan')))

    def test_non_normalized_rejected(self):
        self.altered(lambda p,r,s:p['predictions'][0]['arms']['bridge_image_only'].__setitem__(0,0.6))

    def test_boolean_probability_rejected(self):
        self.altered(lambda p,r,s:p['predictions'][0]['arms']['bridge_image_only'].__setitem__(0,True))

    def test_masked_identity_must_match(self):
        self.altered(lambda p,r,s:p['predictions'][0]['arms']['image_masked'].__setitem__(0,0.41))

    def test_calibration_must_be_text(self):
        self.altered(lambda p,r,s:p['fit'].__setitem__('calibration_selected_weight',0.25))

    def test_calibration_boolean_rejected(self):
        self.altered(lambda p,r,s:p['fit'].__setitem__('calibration_selected_weight',False))

    def test_future_claim_rejected(self):
        self.altered(lambda p,r,s:p.__setitem__('same_source_public_release_not_future',False))

    def test_promotion_claim_rejected(self):
        self.altered(lambda p,r,s:r.__setitem__('stem_winner','trained_image'))

    def test_fake_independent_ground_truth(self):
        self.altered(lambda p,r,s:r.__setitem__('external_ground_truth_independent_owner',True))

    def test_forged_review_improvement(self):
        def mutate(p,r,s):
            r['arms']['bridge_image_only']['correct']=1
            r['arms']['bridge_image_only']['accuracy']=1/64
        self.altered(mutate)

    def test_mcnemar_wrong(self):
        self.altered(lambda p,r,s:r['paired_vs_text_only']['bridge_image_only'].__setitem__('mcnemar_unadjusted_exact_p',0.01))

    def test_boolean_reviewer_count(self):
        self.altered(lambda p,r,s:r['arms']['text_only'].__setitem__('correct',False))

    def test_pairwise_exact_p(self):
        self.assertEqual(v.exact_p(0,0),1)
        self.assertEqual(v.exact_p(3,0),0.25)
        self.assertEqual(v.exact_p(14,7),0.18924713134765625)

    def test_pairwise_interval_full_enumeration(self):
        for r in range(3):
            for h in range(3):
                for wrong in range(3):
                    diff=r+h+wrong
                    for s in range(diff+1):
                        # Enumerate all unknown assignments of historical
                        # correctness categories over the source-blind cases.
                        assignments=set(itertools.permutations('R'*r+'H'*h+'W'*wrong))
                        outcomes=[sum(1 if t=='R' else -1 if t=='H' else 0 for t in a[:s]) for a in assignments]
                        out=v.primary_interval(4,r,h,diff,s)
                        self.assertEqual((out['minimum_consistent_correct'],out['maximum_consistent_correct']),
                                         (4+min(outcomes),4+max(outcomes)))

    def test_duplicate_aggregate_arm(self):
        self.altered(lambda p,r,s:p['arms'].append('text_only'))

    def test_wrong_base_review_accuracy(self):
        self.altered(lambda p,r,s:r['arms']['text_only'].__setitem__('accuracy',1.0))

    def test_pair_rescue_exceeds_predictions(self):
        def mutate(p,r,s):
            r['paired_vs_text_only']['train_gate'].update({'rescued_errors_vs_text':1,'discordant_cases':1,
                'mcnemar_unadjusted_exact_p':1.0})
        self.altered(mutate)


class OriginalMaterial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=os.environ.get('HEPTA_V24_ORIGINAL_ZIP')
        if not p:
            raise RuntimeError('HEPTA_V24_ORIGINAL_ZIP is mandatory for OriginalMaterial (no skip or fixture fallback)')
        cls.path=Path(p)

    def test_genuine_immutable_archive_and_negative(self):
        pred,review,seals=v.verify_archive(self.path)
        doc=v.analyze(pred,review,seals)
        self.assertEqual(doc['cases'],64)
        self.assertEqual(doc['claimed_source_groups'],64)
        self.assertEqual(doc['arm_diagnostics']['train_gate']['changed_top1_vs_text'],38)
        self.assertEqual(doc['arm_diagnostics']['train_gate']['historical_rescues_reported'],14)
        self.assertEqual(doc['arm_diagnostics']['train_gate']['historical_harms_reported'],7)
        self.assertEqual(doc['arm_diagnostics']['bridge_image_only']['changed_top1_vs_text'],50)
        self.assertEqual(doc['text_margin_conditional_image_route']['conditional_image_calls_planned'],21)
        self.assertEqual(doc['text_margin_conditional_image_route']['changed_top1_after_conditional_route'],19)
        self.assertEqual((doc['text_margin_conditional_image_route']['pairwise_only_bounds_reported_by_original_reviewer']['minimum_consistent_correct'],
                          doc['text_margin_conditional_image_route']['pairwise_only_bounds_reported_by_original_reviewer']['maximum_consistent_correct']),(5,33))
        self.assertIsNone(doc['text_margin_conditional_image_route']['actual_conditional_route_accuracy'])
        self.assertFalse(doc['scientific_promotion_authorized'])

    def test_corrupted_original_archive_is_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=bytearray(self.path.read_bytes());b[140]^=0x20
            changed=Path(tmp)/'corrupt.zip';changed.write_bytes(b)
            with self.assertRaises(v.Invalid):v.verify_archive(changed)

    def test_repeat_original_receipt_byte_identity_and_create_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a.json';b=Path(tmp)/'b.json'
            v.run(self.path,a);v.run(self.path,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            with self.assertRaises(FileExistsError):v.run(self.path,a)

    def test_original_in_memory_tamper_denied(self):
        p,r,s=v.verify_archive(self.path)
        r['paired_vs_text_only']['train_gate']['rescued_errors_vs_text']=15
        with self.assertRaises(v.Invalid):v.analyze(p,r,s)


if __name__ == '__main__':unittest.main()
