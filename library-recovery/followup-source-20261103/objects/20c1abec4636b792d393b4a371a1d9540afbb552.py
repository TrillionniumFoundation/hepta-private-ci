"""Source-/score-fenced integrity tests; never grants selection authority."""
from __future__ import annotations
import copy
import unittest
import zipfile
import json
from pathlib import Path
from audit_redacted import read_receipt, check, compare, Reject
ROOT=Path(__file__).resolve().parent
DATA=Path('/mnt/data')

class TestRedactedReceipts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old,_=read_receipt(DATA/'granite2331-redacted-20261015.zip')
        cls.new,_=read_receipt(DATA/'granite2344-redacted-20261015.zip')

    def denied(self,obj):
        with self.assertRaises(Reject):check(obj)

    def test_real_pair_matches_descriptively_only(self):
        r=compare(self.old,self.new)
        self.assertTrue(r['numerical_descriptive_outputs_equal'])
        self.assertFalse(r['encoder_json_bytes_equal'])
        self.assertEqual(r['scores']['adaptive_split']['split_count'],0)
        self.assertEqual(r['scores']['fixed_router']['split_count'],3)
        self.assertEqual(r['production_admission'],'BLOCKED')

    def test_adaptive_equals_continued(self):
        d=check(self.new)
        for k in ('mean_brier_1','mean_brier_2','mean_accuracy_1','mean_accuracy_2'):
            self.assertEqual(d['five_arm_scores']['adaptive_split'][k],d['five_arm_scores']['unsplit_continued_update'][k])

    def test_reject_forged_future_verdict(self):
        t=copy.deepcopy(self.new)
        t['prospective_future_windows_verified']=True
        self.denied(t)

    def test_reject_forged_production(self):
        t=copy.deepcopy(self.new)
        t['production_admission']='ALLOWED'
        self.denied(t)

    def test_reject_nan_probability(self):
        t=copy.deepcopy(self.new)
        t['aggregate']['five_arm_retrospective_research'][0]['test_1']['brier']=float('nan')
        self.denied(t)

    def test_reject_missing_arm(self):
        t=copy.deepcopy(self.new)
        t['aggregate']['five_arm_retrospective_research'].pop()
        self.denied(t)

    def test_reject_duplicate_arm(self):
        t=copy.deepcopy(self.new)
        t['aggregate']['five_arm_retrospective_research'][1]=copy.deepcopy(t['aggregate']['five_arm_retrospective_research'][0])
        self.denied(t)

    def test_reject_mismatched_model(self):
        t=copy.deepcopy(self.new)
        t['aggregate']['registered_encoder']='fictional-model'
        self.denied(t)

    def test_reject_duplicate_file_sha_entry(self):
        t=copy.deepcopy(self.new)
        t['files'][1]['name']=t['files'][0]['name']
        self.denied(t)

    def test_reject_wrong_source_sha(self):
        t=copy.deepcopy(self.new)
        t['files'][0]['sha256']='a'*64
        # It can have an arbitrary file digest; ensure panel bytes in particular bound.
        for f in t['files']:
            if f['name']=='source-panel.json':f['sha256']='b'*64
        self.denied(t)

    def test_pair_comparison_rejects_score_tamper_even_same_source(self):
        t=copy.deepcopy(self.new)
        t['aggregate']['five_arm_retrospective_research'][0]['test_1']['brier']+=0.01
        with self.assertRaises(Reject):compare(self.old,t)

    def test_no_raw_json_files_in_zip(self):
        for n in ('2331','2344'):
            with zipfile.ZipFile(DATA/f'granite{n}-redacted-20261015.zip') as z:
                self.assertEqual(z.namelist(),['granite-redacted-receipt.json'])

    def test_seed_repeat_not_independent_source_multiplier(self):
        r=compare(self.old,self.new)
        self.assertTrue(r['three_training_seeds_one_dataset'] if 'three_training_seeds_one_dataset' in r else r['study'].endswith('only'))
        self.assertFalse(r['classification_quality_and_longitudinal_gain_established'])

if __name__=='__main__':unittest.main()
