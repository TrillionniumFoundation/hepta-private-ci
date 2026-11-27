"""Structural, mathematical and genuine-source shared-policy tests."""
from __future__ import annotations
import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compile_policy import (SharedPolicy, binding, compact, compile_one, incremental_break_even, key, validate_graph)
from benchmark import config, lifecycle, run
from audit_compiled import audit, verify_table
from study import config as parent_config
from material_news import encode, loads, packet, prepare, sha
from online import setup


def scenario(**extra):
    return {'name':'test','horizon':1,'step_fee':'1/1000','calibration_fee':'0','budget':32}|extra


class MathTests(unittest.TestCase):
    def test_01_history_boolean_rejected(self):
        with self.assertRaises(ValueError):key((True,))
    def test_02_bad_scope_digest(self):
        with self.assertRaises(ValueError):binding('X'*64,'0'*64)
    def test_03_all_children_present(self):
        rows,_=compile_one(((2,14,15,15),),scenario(),'neutral')
        validate_graph(rows,32)
        del rows['0']
        with self.assertRaises(ValueError):validate_graph(rows,32)
    def test_04_extra_unreachable_node(self):
        rows,_=compile_one(((8,8,8,8),),scenario(),'neutral')
        rows['0']=copy.deepcopy(rows[''])
        with self.assertRaises(ValueError):validate_graph(rows,32)
    def test_05_unexecuted_selection(self):
        rows,_=compile_one(((8,8,8,8),),scenario(),'neutral');rows['']['selected_steps']=128
        with self.assertRaises(ValueError):validate_graph(rows,32)
    def test_06_pruned_cannot_execute(self):
        rows,_=compile_one(((2,14,15,15),),scenario(),'neutral');rows['']['pruned']=True
        with self.assertRaises(ValueError):validate_graph(rows,32)
    def test_07_nonfinite_value_rejected(self):
        rows,_=compile_one(((8,8,8,8),),scenario(),'neutral');rows['']['value']=float('nan')
        with self.assertRaises(ValueError):validate_graph(rows,32)
    def test_08_unknown_node_fields(self):
        rows,_=compile_one(((8,8,8,8),),scenario(),'neutral');rows['']['new_reward']=1
        with self.assertRaises(ValueError):validate_graph(rows,32)
    def test_09_exact_rational_all_profiles(self):
        curves=((3,12,14,14),(4,9,10,10));s=scenario()
        data={'curves':curves,'scenarios':[s],'tables':{}}
        for mode in ('neutral','fixed','ndu'):
            data['tables']['test/'+mode]=compile_one(curves,s,mode)[0]
        self.assertGreater(verify_table(data),0)
    def test_10_delayed_gain_policy_preserved(self):
        rows,_=compile_one(((8,8,16,16),),scenario(step_fee='1/10000'),'neutral')
        self.assertEqual(rows['']['action'],'continue')
        self.assertEqual(rows['4']['action'],'continue')
    def test_11_no_marginal_saving_never_amortizes(self):
        self.assertIsNone(incremental_break_even(100,2,3))
        self.assertIsNone(incremental_break_even(100,2,2))
    def test_12_strict_break_even(self):
        self.assertEqual(incremental_break_even(100,20,10),11)
    def test_13_invalid_costs(self):
        for x in (True,-1,float('nan')):
            with self.assertRaises(ValueError):incremental_break_even(x,2,1)
    def test_14_numeric_tamper_rational_auditor(self):
        s=scenario();rows,_=compile_one(((8,8,8,8),),s,'neutral');rows['']['value']+=1
        d={'curves':((8,8,8,8),),'scenarios':[s], 'tables':{'test/'+m:copy.deepcopy(rows) for m in ('neutral','fixed','ndu')}}
        with self.assertRaises(ValueError):verify_table(d)


class OriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.archive=Path(os.environ['NEWS_ARCHIVE']);cls.material=cls.root/'material'
        prepare(cls.archive,cls.material)
        with contextlib.redirect_stdout(io.StringIO()):cls.seal=run(cls.material,cls.root/'run')
        cls.prior=loads((cls.root/'run/prior.json').read_bytes());cls.a,cls.receipt=packet(cls.material/'worker.npz')
        _,_,cls.x=setup(cls.a)
        cls.asset=SharedPolicy(cls.root/'run/policy.json',cls.seal['compilation']['asset_sha256'],
                              cls.receipt['worker_sha256'],cls.seal['prior_sha256'])
        cls.scenario=parent_config()['scenarios'][0]
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_15_complete_campaign(self):
        self.assertEqual(len(self.seal['rows']),84)
        self.assertEqual(self.seal['prior_fits_physically_executed'],1)
    def test_16_one_immutable_owner(self):
        a=self.asset.bind(self.asset.scope_digest,self.scenario,'ndu')
        b=self.asset.bind(self.asset.scope_digest,self.scenario,'ndu')
        self.assertIs(a.owner.tables,b.owner.tables)
        with self.assertRaises(TypeError):a.owner.tables[a.name]['']['action']='stop'
    def test_17_returned_record_not_mutable_owner(self):
        b=self.asset.bind(self.asset.scope_digest,self.scenario,'ndu')
        x=b.decision((),0);x['posterior'][0]=999
        self.assertNotEqual(b.decision((),0)['posterior'][0],999)
    def test_18_lookup_no_solver_constructor(self):
        with patch('compile_policy.Planner',side_effect=AssertionError('online solver')):
            b=self.asset.bind(self.asset.scope_digest,self.scenario,'ndu');b.decision((),0)
    def test_19_real_shared_lifecycle_no_solver(self):
        with patch('benchmark.Planner',side_effect=AssertionError('online solver')):
            r=lifecycle(self.a,self.x,self.prior,self.asset,'shared_ndu',self.scenario,lambda e:None)
        self.assertEqual(r['solver_constructions'],0);self.assertEqual(r['online_model_nodes'],0)
    def test_20_stale_scope_refused(self):
        with self.assertRaises(ValueError):self.asset.bind('0'*64,self.scenario,'ndu')
    def test_21_changed_tariff_refused(self):
        with self.assertRaises(ValueError):self.asset.bind(self.asset.scope_digest,self.scenario|{'step_fee':'0'},'ndu')
    def test_22_checkpoint_drift_refused(self):
        b=self.asset.bind(self.asset.scope_digest,self.scenario,'ndu')
        with self.assertRaises(ValueError):b.decision((4,),0)
        with self.assertRaises(ValueError):b.decision((),True)
    def test_23_asset_bytes_tampered(self):
        p=self.root/'bad-asset.json';p.write_bytes((self.root/'run/policy.json').read_bytes()+b' ')
        with self.assertRaises(ValueError):SharedPolicy(p,self.seal['compilation']['asset_sha256'],self.receipt['worker_sha256'],self.seal['prior_sha256'])
    def test_24_prior_scope_changed(self):
        with self.assertRaises(ValueError):SharedPolicy(self.root/'run/policy.json',self.seal['compilation']['asset_sha256'],self.receipt['worker_sha256'],'0'*64)
    def test_25_budget_refusal_zero_gradients(self):
        s=next(s for s in parent_config()['scenarios'] if s['name']=='budget7')
        with patch('benchmark.Trainer.step',side_effect=AssertionError('unaffordable update')):
            r=lifecycle(self.a,self.x,self.prior,self.asset,'shared_ndu',s,lambda e:None)
        self.assertEqual(r['actual_steps'],0);self.assertEqual(r['calibration_calls'],0)
    def test_26_complete_original_independent_audit(self):
        r=audit(self.archive,self.material,self.root/'run',self.root/'audit.json')
        self.assertEqual(r['verified_lifecycles'],84);self.assertEqual(r['paired_shared_vs_solve'],24)
        self.assertFalse(r['cross_task_transfer_verified'])
    def test_27_model_decision_parity(self):
        for row in self.seal['rows']:
            if not row['arm'].startswith('shared_'):continue
            other=next(r for r in self.seal['rows'] if (r['arm'],r['scenario'],r['repeat'])==('solve_'+row['arm'][7:],row['scenario'],row['repeat']))
            for field in ('weights','probabilities','events','losses'):
                self.assertEqual(row[field],other[field])
    def test_28_interruption_cannot_seal(self):
        with patch('benchmark.Trainer.step',side_effect=RuntimeError('injected update failure')):
            with self.assertRaises(RuntimeError),contextlib.redirect_stdout(io.StringIO()):run(self.material,self.root/'failed')
        self.assertFalse((self.root/'failed/sealed.json').exists())
        self.assertIn(b'failure',(self.root/'failed/journal.jsonl').read_bytes())
    def test_29_no_overwrite_successful_run(self):
        before=(self.root/'run/sealed.json').read_bytes()
        with self.assertRaises(FileExistsError):run(self.material,self.root/'run')
        self.assertEqual(before,(self.root/'run/sealed.json').read_bytes())
    def test_30_unknown_table_field_rejected_even_rehashed(self):
        obj=loads((self.root/'run/policy.json').read_bytes());obj['promotion']=True
        p=self.root/'unknown.json';p.write_bytes(encode(obj))
        with self.assertRaises(ValueError):SharedPolicy(p,sha(p.read_bytes()),self.receipt['worker_sha256'],self.seal['prior_sha256'])
    def test_31_new_worker_packet_not_transfer(self):
        with self.assertRaises(ValueError):SharedPolicy(self.root/'run/policy.json',self.seal['compilation']['asset_sha256'],'1'*64,self.seal['prior_sha256'])
    def test_32_no_extra_head_weights_in_control_asset(self):
        obj=loads((self.root/'run/policy.json').read_bytes())
        self.assertNotIn('weights',obj);self.assertNotIn('checkpoints',obj)
        self.assertEqual(len(obj['tables']),12)

    def rejected_run(self, change):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'run';shutil.copytree(self.root/'run',path)
            value=loads((path/'sealed.json').read_bytes());change(value)
            (path/'sealed.json').write_bytes(encode(value))
            with self.assertRaises(ValueError):audit(self.archive,self.material,path,Path(tmp)/'audit.json')
    def test_33_hidden_solver_count_refused(self):
        def change(s):
            next(r for r in s['rows'] if r['arm']=='shared_ndu')['solver_constructions']=1
        self.rejected_run(change)
    def test_34_unpaid_physical_update_refused(self):
        def change(s):
            next(r for r in s['rows'] if r['arm']=='shared_ndu')['actual_steps']=0
        self.rejected_run(change)
    def test_35_double_counted_prior_refused(self):
        self.rejected_run(lambda s:s.update(prior_fits_physically_executed=84))
    def test_36_fake_new_source_claim_refused(self):
        self.rejected_run(lambda s:s.update(new_sources=32))


if __name__=='__main__':unittest.main()
