"""Independent evidence regression and deliberate tamper refusals."""
import copy
from pathlib import Path
import unittest
from .audit_cpu_matched_v2 import audit,load_raw,UnresolvedAudit

BUNDLE=Path(__file__).resolve().parent/'TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json.gz.b64'

class TestIndependentAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=load_raw(BUNDLE)

    def test_no_drop_and_negative_result_retained(self):
        s=audit(self.data)
        self.assertEqual(s['record_count'],12)
        self.assertEqual(s['pairs'],6)
        self.assertLess(s['cpu_gap_max_pct'],.05)
        self.assertFalse(s['scientific_gate_closed'])
        by={(r['task'],r['split']):r for r in s['table']}
        self.assertLess(by[('copy','ood')]['timed_minus_aggregate_pp'],-20)
        self.assertLess(abs(by[('mqar4','ood')]['timed_minus_aggregate_pp']),2)

    def test_missing_duplicate_and_unmatched_model_refused(self):
        for edit in ('missing','duplicate','data','initial'):
            d=copy.deepcopy(self.data)
            if edit=='missing': d['records'].pop()
            if edit=='duplicate': d['records'][0]=d['records'][1]
            if edit=='data': d['records'][1]['train_data_sha256']='f'*64
            if edit=='initial': d['records'][1]['initial_model_sha256']='f'*64
            with self.subTest(edit=edit),self.assertRaises(UnresolvedAudit):audit(d)

    def test_cpu_hard_budget_and_forged_metric_refused(self):
        for field,value in (('training_cpu_seconds',20.),('optimizer_steps',8000),('production_activation',True)):
            d=copy.deepcopy(self.data);d['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(UnresolvedAudit):audit(d)
        d=copy.deepcopy(self.data);d['records'][0]['id']['accuracy']=1.
        with self.assertRaises(UnresolvedAudit):audit(d)

    def test_summary_and_safety_flag_tampering_refused(self):
        d=copy.deepcopy(self.data);d['comparisons'][0]['ood_signed_pp']=500
        with self.assertRaises(UnresolvedAudit):audit(d)
        d=copy.deepcopy(self.data);d['all_scientific_blockers_closed']=True
        with self.assertRaises(UnresolvedAudit):audit(d)

if __name__=='__main__':unittest.main()
