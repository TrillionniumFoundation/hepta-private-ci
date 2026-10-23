"""P43 adversarial contract tests. Synthetic fixtures never qualify research."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import paired_gain_audit as gate


def h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def fixture(cheap_all_correct=False):
    rows, head = [], []
    for block in range(64):
        images = (1000+2*block, 1001+2*block)
        captions = (5000+2*block, 5001+2*block)
        for j, (ii, ci, y) in enumerate(((0, 0, 1), (0, 1, 0), (1, 1, 1), (1, 0, 0))):
            image, cap = images[ii], captions[ci]
            rid = h(f"row:{block}:{j}")
            wrong = (not cheap_all_correct and j == 0)
            cheap = int(not y) if wrong else y
            p = .80 if cheap else .20
            item = {"row_id":rid, "image_id":image, "caption_id":cap,
                    "pair_block_id":h(f"block:{block}"),"label":y,
                    "image_sha256":h(f"photo:{image}"),
                    "caption_sha256":h(f"caption:{cap}"),
                    "frozen_cosine": .7 if y else .1,
                    "cheap_probability_positive":p,
                    "cheap_prediction":cheap,"cheap_accepted":True,
                    "learned_prediction":y,"learned_correct":True}
            rows.append(item)
            head.append({"schema":"hepta.prediction-ledger.v1", "source_id":rid,
                         "label":y,"split":"test", "arm":"text_image-gated",
                         "intervention":"paired","pair_block_id":item["pair_block_id"],
                         "image_group_id":f"coco2017:{image}",
                         "confidence_threshold":.7,"temperature":.25,"prediction":y,"accepted":True,
                         "probabilities":[.05,.95] if y else [.95,.05],
                         "identity":dict(gate.PRIMARY_IDENTITY)})
    metric=gate.metrics([r['label'] for r in rows],
                        [r['cheap_prediction'] for r in rows],
                        [r['cheap_accepted'] for r in rows])
    cheap_nll=float(-np.mean([np.log(.8) if r['cheap_prediction']==r['label']
                              else np.log(.2) for r in rows]))
    plan={"schema":"hepta.cheap-cosine-control-plan.v1",
          "original_archive_sha256":gate.ARCHIVE_SHA256,
          "data_sha256":gate.DATA_SHA256,"feature_bank_sha256":gate.BANK_SHA256,
          "trainable_scalar_parameters":2,"temperature_candidates":[.25,.5,1.],
          "threshold":.7,"new_blind_trial":False,
          "authority":"DENY_ALL","production_activation_allowed":False}
    report={"schema":"hepta.cheap-cosine-control-result.v1",
            "plan_sha256":hashlib.sha256(gate.canon(plan)).hexdigest(),
            "cohorts":{"test":{"rows":256,"pair_blocks":64}},
            "calibration_temperature":.25,
            "split_metrics":{"test":{**metric,"nll":cheap_nll,
                                    "confidence_threshold":.7}},
            "original_trained_head_correct":256,
            "paired_learned_head_vs_cheap_cosine":{
                "pair_blocks":64,"new_independent_trial":False,
                "learned_minus_cheap_accuracy":1-metric['accuracy']},
            "new_blind_trial":False,"semantic_quality_qualified":False,
            "authority":"DENY_ALL","production_activation_allowed":False}
    return plan,report,rows,head


class PairedGainAuditTests(unittest.TestCase):
    def test_complete_rigorous_screen_does_not_grant_authority(self):
        plan, report, rows, head = fixture()
        gate.check_plan(plan,report)
        d=gate.verified_pairs(rows,head)
        got=gate.recompute(report,d)
        self.assertTrue(got['research_screen']['historical_posthoc_criteria_met'])
        self.assertEqual(got['admission'],'HOLD_NO_GO')
        self.assertFalse(got['eligible_for_production'])
        self.assertEqual(got['observed']['trained_head']['correct'],256)
        self.assertEqual(got['observed']['cheap_cosine']['correct'],192)
        self.assertEqual(got['observed']['paired']['pair_blocks'],64)

    def test_strong_cheap_baseline_rejects_unearned_head_gain(self):
        plan,report,rows,head=fixture(cheap_all_correct=True)
        got=gate.recompute(report,gate.verified_pairs(rows,head))
        self.assertFalse(got['research_screen']['historical_posthoc_criteria_met'])
        self.assertFalse(got['eligible_for_production'])

    def test_giant_json_integer_does_not_overflow(self):
        with self.assertRaises(gate.AuditError):gate.number(10**401)

    def test_bool_is_not_numeric(self):
        with self.assertRaises(gate.AuditError):gate.number(True)

    def test_cross_block_photo_is_rejected(self):
        *_,rows,head=fixture()
        rows[4]['image_id']=rows[0]['image_id']
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_cross_block_duplicate_bytes_is_rejected(self):
        *_,rows,head=fixture()
        for r in rows[4:8]:
            if r['image_id']==1002:r['image_sha256']=rows[0]['image_sha256']
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_image_id_cannot_change_its_byte_hash_within_block(self):
        *_,rows,head=fixture()
        rows[0]['image_sha256']=h('forged bytes')
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_caption_id_cannot_change_its_byte_hash_within_block(self):
        *_,rows,head=fixture()
        rows[0]['caption_sha256']=h('forged caption bytes')
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_reused_caption_bytes_across_blocks_rejected(self):
        *_,rows,head=fixture()
        for r in rows[4:8]:
            if r['caption_id']==5002:r['caption_sha256']=rows[0]['caption_sha256']
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_original_head_digest_cannot_be_switched(self):
        *_,rows,head=fixture()
        head[0]['identity']['head_sha256']='0'*64
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_original_prediction_reader_rejects_symlink_and_oversize(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'source'
            p.write_bytes(b'x'*512_001)
            with self.assertRaises(gate.AuditError):gate.verified_primary(p)
            p.write_bytes(b'[]')
            link=Path(t)/'alias'
            link.symlink_to(p)
            with self.assertRaises(gate.AuditError):gate.verified_primary(link)

    def test_duplicate_or_missing_row_is_rejected(self):
        *_,rows,head=fixture()
        rows.pop()
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_fake_label_not_supported_by_source_prediction(self):
        *_,rows,head=fixture()
        rows[0]['label']=0
        rows[0]['learned_correct']=False
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_forged_negative_acceptance_rejected(self):
        *_,rows,head=fixture()
        rows[0]['cheap_accepted']=False
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_head_probabilities_must_justify_decision(self):
        *_,rows,head=fixture()
        head[0]['probabilities']=[.95,.05]
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_head_detection_cannot_be_claimed_from_wrong_row(self):
        *_,rows,head=fixture()
        head[0]['source_id']=h('new source id')
        with self.assertRaises(gate.AuditError):gate.verified_pairs(rows,head)

    def test_incorrect_reported_gain_rejected(self):
        _,report,rows,head=fixture()
        report['paired_learned_head_vs_cheap_cosine']['learned_minus_cheap_accuracy']=.9
        with self.assertRaises(gate.AuditError):gate.recompute(report,gate.verified_pairs(rows,head))

    def test_self_claimed_production_pass_rejected(self):
        plan,report,*_=fixture()
        report['production_activation_allowed']=True
        with self.assertRaises(gate.AuditError):gate.check_plan(plan,report)

    def test_arbitrary_temperature_rejected(self):
        plan,report,*_=fixture()
        report['calibration_temperature']=.3
        with self.assertRaises(gate.AuditError):gate.check_plan(plan,report)

    def test_bound_source_blob_and_full_cli_output(self):
        plan,report,rows,head=fixture()
        with tempfile.TemporaryDirectory() as t:
            paths={}
            for name, obj in [('plan',plan),('report',report),('rows',rows),('primary',head)]:
                f=Path(t)/(name+'.json')
                f.write_bytes(gate.canon(obj)+b'\n')
                paths[name]=f
            original=paths['primary'].read_bytes()
            valid_hash=hashlib.sha1(b'blob '+str(len(original)).encode()+b'\0'+original).hexdigest()
            with patch.object(gate,'ORIGINAL_PRIMARY_BLOB_SHA1',valid_hash):
                output=Path(t)/'audit.json'
                got=gate.run(paths['plan'],paths['report'],paths['rows'],paths['primary'],output)
                self.assertEqual(json.loads(output.read_text())['admission'],'HOLD_NO_GO')
                self.assertEqual(got['observed']['trained_head']['correct'],256)
                self.assertEqual(got['source']['original_head_prediction_git_blob'],valid_hash)
            paths['primary'].write_bytes(original+b' ')
            with self.assertRaises(gate.AuditError):gate.verified_primary(paths['primary'])


if __name__=='__main__': unittest.main()
