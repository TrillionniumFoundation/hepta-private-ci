"""Tamper regressions on sanitized physical receipt; never fake natural-model outcomes."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import unittest
from v14_public_cost_audit import verify

HERE=Path(__file__).parent
DOC=json.loads((HERE/'STEM_V14_ORIGINAL_PRIMARY_COST_20261016.json').read_text())
V13=(HERE/'STEM_V13_CHEAP_RETRIEVAL_20261015.json').read_bytes()

class Auditor(unittest.TestCase):
    def test_actual_public(self):
        a=verify(DOC,V13)
        self.assertEqual(a['status'],'NO_GO')
        self.assertGreater(a['cpu_primary_to_bm25_ratio'],1)
    def bad(self,keys,value):
        x=copy.deepcopy(DOC);p=x
        for k in keys[:-1]:p=p[k]
        p[keys[-1]]=value
        with self.assertRaises(ValueError):verify(x,V13)
    def test_fake_semantic(self):self.bad(['independent_human_semantic_correctness'],1)
    def test_fake_production(self):self.bad(['production_authorized'],True)
    def test_fake_model_selection(self):self.bad(['model_selected'],True)
    def test_fake_calendar(self):self.bad(['number_of_new_prospective_calendar_windows'],1)
    def test_fake_lifecycle(self):self.bad(['v11_trained_head_equal_full_lifecycle_cost'],True)
    def test_unknown_family(self):self.bad(['original_heldout_roots'],829)
    def test_gained_without_loss(self):self.bad(['original_heldout_weak_evidence_proxy','per_family','conv-48','loss'],0)
    def test_tamper_original_dataset(self):self.bad(['original_dataset_sha256'],'0'*64)
    def test_rename_arm(self):self.bad(['registered_primary'],'char_only')
    def test_false_rank_parity(self):self.bad(['route_parity','exact_original_primary_top32'],1985)
    def test_missing_cost_run(self):self.bad(['physical_cost','primary_only','experiments'],DOC['physical_cost']['primary_only']['experiments'][:1])
    def test_zero_cpu_fabricated(self):
        self.bad(['physical_cost','primary_only','experiments'],[{'cpu_ns':0,**{k:v for k,v in x.items() if k!='cpu_ns'}} for x in DOC['physical_cost']['primary_only']['experiments']])
    def test_miscount_top16(self):self.bad(['original_heldout_weak_evidence_proxy','primary_any_hit16'],999)
    def test_swap_baseline_model(self):self.bad(['original_heldout_weak_evidence_proxy','bm25_any_hit3'],380)
    def test_missing_model_calls(self):self.bad(['reader_generated_new_outputs'],32)
    def test_corrupted_v13_reference(self):
        with self.assertRaises(ValueError):verify(DOC,V13+b' ')
    def test_extra_field(self):
        x=copy.deepcopy(DOC);x['final_use_authorized']=True
        with self.assertRaises(ValueError):verify(x,V13)
if __name__=='__main__':unittest.main()
