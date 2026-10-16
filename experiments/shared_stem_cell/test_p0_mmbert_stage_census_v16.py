"""Synthetic/stdlib stage-diagnostic regressions; no model-origin claim."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from p0_mmbert_stage_census_v16 import (
    Invalid, REVISION, SCHEMA, STAGES, StageLedger, read_preflight,
    strict_pairs, write_create_only)

HEAD = 'a' * 40


def valid_preflight():
    return {'schema': 'hepta.p0.independent-model-preflight-observations.v9',
            'requested_models': ['mmbert_small'], 'scoped_single_candidate': True,
            'models': {'mmbert_small': {'status':'source_materialized_not_model_qualified',
                'snapshot_source':'original_hub_revision',
                'source_revision': REVISION,
                'publisher_lfs_files_checked': 3,
                'complete_model_parameter_loading_verified_by_this_preflight': False}},
            'whole_four_model_success': False, 'human_labels_accessed': False,
            'production_promotion_permitted': False, 'authority':'DENY_ALL'}


class SourceStageDiagnostics(unittest.TestCase):
    def test_finished_diagnostic_still_denies_production(self):
        led = StageLedger(HEAD, 34, 'source')
        for stage in STAGES:
            self.assertEqual(led.perform(stage,lambda: 'observed'), 'observed')
        r = led.receipt()
        self.assertEqual(r['outcome'], 'all_stages_passed')
        self.assertEqual(r['ordered_completed_stages'], list(STAGES))
        self.assertFalse(r['production_promotion_permitted'])
        self.assertFalse(r['physical_source_signer_independently_verified'])
        self.assertFalse(r['full_four_stem_original_human_efficacy_verified'])
        self.assertEqual(r['authority'], 'DENY_ALL')

    def test_every_failure_stage_preserves_prior_boundaries(self):
        for index,stage in enumerate(STAGES):
            with self.subTest(stage=stage):
                led=StageLedger(HEAD, 34, 'merge')
                for previous in STAGES[:index]:led.perform(previous,lambda: True)
                def fail():raise Invalid('do not serialize real exception text or tensors')
                with self.assertRaises(Invalid):led.perform(stage,fail)
                r=led.receipt()
                self.assertEqual(r['first_failed_stage'],stage)
                self.assertEqual(r['ordered_completed_stages'],list(STAGES[:index]))
                self.assertEqual(r['exception_class_only'],'Invalid')
                self.assertEqual(r['outcome'],'stage_failed')
                self.assertNotIn('do not serialize',json.dumps(r))
                self.assertNotIn('task_accuracy',r)
                self.assertFalse(r['production_promotion_permitted'])
                with self.assertRaises(Invalid):led.perform(stage,lambda: None)

    def test_out_of_order_duplicate_and_missing_boundaries_denied(self):
        led=StageLedger(HEAD,1,'source')
        with self.assertRaises(Invalid):led.perform(STAGES[1],lambda:True)
        self.assertEqual(led.receipt()['outcome'],'incomplete')
        led.perform(STAGES[0],lambda: True)
        with self.assertRaises(Invalid):led.perform(STAGES[0],lambda:True)

    def test_injected_exception_raises_and_is_not_converted_to_success(self):
        led=StageLedger(HEAD,3,'source')
        def fail():raise FileNotFoundError('/private/model/path')
        with self.assertRaises(FileNotFoundError):led.perform(STAGES[0],fail)
        r=led.receipt()
        self.assertEqual(r['exception_class_only'],'FileNotFoundError')
        self.assertNotIn('/private',json.dumps(r))
        self.assertEqual(r['outcome'],'stage_failed')

    def test_source_run_identity_requirements(self):
        for args in ((HEAD,0,'source'),('bad',4,'source'),(HEAD,True,'source'),
                     (HEAD,2,'invalid'),(HEAD,2,'SOURCE')):
            with self.subTest(args=args),self.assertRaises(Invalid):StageLedger(*args)
        self.assertEqual(StageLedger(HEAD,3,'merge').receipt()['exact_source_head'],HEAD)

    def write_doc(self, root, value):
        path=Path(root)/'preflight.json'
        path.write_text(json.dumps(value,sort_keys=True),encoding='utf8')
        return path

    def test_valid_source_preflight_is_sha_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            path=self.write_doc(temp,valid_preflight())
            data,sha=read_preflight(path)
            self.assertEqual(sha,hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(data['models']['mmbert_small']['source_revision'],REVISION)

    def test_original_source_revision_and_lfs_cannot_be_downgraded(self):
        for key,value in (('source_revision','f'*40),('publisher_lfs_files_checked',0),
                          ('status','unavailable'),('snapshot_source','fake'),
                          ('complete_model_parameter_loading_verified_by_this_preflight',True)):
            data=valid_preflight();data['models']['mmbert_small'][key]=value
            with self.subTest(key=key),tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(Invalid):read_preflight(self.write_doc(temp,data))

    def test_no_early_preflight_production_or_labels(self):
        for key,value in (('authority','GRANTED'),('production_promotion_permitted',True),
                          ('human_labels_accessed',True),('whole_four_model_success',True),
                          ('scoped_single_candidate',False)):
            data=valid_preflight();data[key]=value
            with self.subTest(key=key),tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(Invalid):read_preflight(self.write_doc(temp,data))

    def test_duplicate_json_keys_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'preflight.json';p.write_text('{"x": 1, "x": 2}',encoding='utf8')
            with self.assertRaises(Invalid):read_preflight(p)
        with self.assertRaises(Invalid):strict_pairs([('x',1),('x',2)])

    def test_unexpected_source_inventory_refused(self):
        for update in ({'requested_models':['granite_97m_r2']},
                       {'schema':'unknown'}, {'models':{}},
                       {'requested_models':['mmbert_small','granite_97m_r2']}):
            val=valid_preflight();val.update(update)
            with tempfile.TemporaryDirectory() as temp,self.assertRaises(Invalid):
                read_preflight(self.write_doc(temp,val))

    def test_symlink_source_and_output_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);p=self.write_doc(temp,valid_preflight())
            sym=base/'preflight-link.json';sym.symlink_to(p)
            with self.assertRaises(Invalid):read_preflight(sym)
            out=base/'result.json';out.symlink_to(base/'missing')
            with self.assertRaises(FileExistsError):write_create_only(out,StageLedger(HEAD,1,'source').receipt())

    def test_create_once_then_cold_reopen_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'diagnostic.json';r=StageLedger(HEAD,12,'merge').receipt()
            write_create_only(p,r)
            self.assertEqual(json.loads(p.read_text()),r)
            with self.assertRaises(FileExistsError):write_create_only(p,r)

    def test_corrupted_nan_or_oversized_receipt_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):write_create_only(Path(temp)/'x.json',{'bad':float('nan')})
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(Invalid):write_create_only(Path(temp)/'x.json',{'big':'x'*30000})

    def test_model_execution_is_not_imported_by_mechanism_suite(self):
        import sys
        self.assertNotIn('transformers',sys.modules)
        self.assertNotIn('p0_mmbert_tied_load_contract_v15',sys.modules)


if __name__=='__main__':unittest.main()
