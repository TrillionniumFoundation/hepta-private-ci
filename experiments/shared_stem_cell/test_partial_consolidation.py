"""Actual selected-component execution; controlled calibration tables are fixtures."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import save_file

from experiments.shared_stem_cell import consolidation as c, execution as e
from experiments.shared_stem_cell import partial_consolidation as p, consolidation_study as s


class PartialTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(71)
        self.cells, self.width, self.classes = 4, 8, 2
        self.teachers = tuple(e.Head(8, 2, 'gated', 8).eval().requires_grad_(False) for _ in range(4))
        self.models = {k: e.Head(12, 2, 'gated', 8).eval().requires_grad_(False)
                       for k in ('shared_frozen', *c.STUDENTS)}
        self.y = torch.tensor([0, 1]*4)
        self.r = torch.arange(4).repeat_interleave(2)
        bank = [[.9,.1]]*8  # one correct per Cell
        good = [[.9,.1],[.1,.9]]*3 + [[.1,.9],[.9,.1]]  # first 3 pass, last fails
        bad = [[.1,.9],[.9,.1]]*4
        probs = {'bank':bank, 'supervised':good, 'shared_frozen':bank, 'mixed':bad, 'distilled':bad}
        self.receipt = {'route_profile':{'cells':4, 'input_width':8},
            'calibration_probabilities':probs, 'calibration_scores':{k:c.score(v,self.y,self.r,4) for k,v in probs.items()},
            'teacher_identities':[e.parameters(t) for t in self.teachers],
            'students':{k:e.parameters(v) for k,v in self.models.items()},
            'parameter_counts':{'bank':sum(e.parameters(t)['parameters'] for t in self.teachers)}, 'selected':'bank'}

    def chosen(self):
        choice = p.select(self.receipt, self.y, self.r)
        policy = choice['policy']
        components = {k:self.models[policy['student']] if k == 'shared' else self.teachers[int(k[5:])]
                      for k in policy['components']}
        return choice, components

    def bindings(self, components):
        return {k:{'scope':'test-only', 'stem_sha256':'1'*64, 'dataset_sha256':'2'*64,
            'feature_profile_sha256': ('3' if k == 'shared' else '4')*64,
            'training_lineage_sha256':'5'*64, 'logical_cell':k, 'generation':1} for k in components}

    def test_partial_selection_retains_failing_cell_and_charges_shared_once(self):
        choice, components = self.chosen()
        self.assertEqual(choice['selected'], 'supervised')
        self.assertEqual(choice['policy']['assignment'], ['shared']*3+['cell-3'])
        self.assertEqual(choice['policy']['parameters'], sum(e.parameters(v)['parameters'] for v in components.values()))
        self.assertLess(choice['policy']['parameters'], self.receipt['parameter_counts']['bank'])
        self.assertEqual(choice['candidates']['supervised']['calibration_score']['correct'], 7)
        self.assertEqual(choice['additional_optimizer_steps'], 0)

    def test_two_cell_shared_plus_fallback_can_be_larger_than_bank(self):
        rec = deepcopy(self.receipt)
        teacher = e.Head(384,4,'gated',8).eval().requires_grad_(False)
        student = e.Head(386,4,'gated',8).eval().requires_grad_(False)
        rec['route_profile'] = {'cells':2,'input_width':384}
        rec['teacher_identities'] = [e.parameters(teacher)]*2
        rec['students'] = {k:e.parameters(student) for k in self.models}
        rec['parameter_counts']['bank'] = 2*e.parameters(teacher)['parameters']
        y,r = torch.tensor([0,1]*2), torch.tensor([0,0,1,1])
        probs = {k:[[.9,.05,.03,.02]]*4 for k in c.ARMS}
        for k in self.models:
            probs[k] = [[.9,.05,.03,.02],[.05,.9,.03,.02],[.05,.9,.03,.02],[.9,.05,.03,.02]]
        rec['calibration_probabilities'] = probs
        rec['calibration_scores'] = {k:c.score(v,y,r,2) for k,v in probs.items()}
        chosen = p.select(rec,y,r)
        self.assertEqual(chosen['selected'], 'bank')
        self.assertTrue(all(not chosen['candidates'][k]['eligible'] for k in self.models))
        self.assertGreater(chosen['candidates']['supervised']['policy']['parameters'], chosen['policy']['parameters'])

    def test_missing_calibration_cell_never_licenses_replacement(self):
        rec = deepcopy(self.receipt)
        rec['calibration_probabilities'] = {k:v[:6] for k,v in rec['calibration_probabilities'].items()}
        rec['calibration_scores'] = {k:c.score(v,self.y[:6],self.r[:6],4) for k,v in rec['calibration_probabilities'].items()}
        chosen = p.select(rec,self.y[:6],self.r[:6])
        self.assertEqual(chosen['policy']['assignment'][-1], 'cell-3')

    def test_no_training_and_source_receipt_unchanged(self):
        before = deepcopy(self.receipt); rng = torch.get_rng_state().clone()
        with patch.object(e,'fit') as fit, patch.object(torch.optim,'AdamW') as opt:
            self.chosen()
        fit.assert_not_called(); opt.assert_not_called()
        self.assertEqual(before,self.receipt); self.assertTrue(torch.equal(rng,torch.get_rng_state()))

    def test_sparse_execution_exactly_one_component_per_row(self):
        chosen, parts = self.chosen(); x=torch.randn(9,8); r=torch.tensor([3,1,0,3,2,0,3,3,1])
        calls=[]; hooks=[v.register_forward_pre_hook(lambda m,args,k=k: calls.append((k,len(args[0])))) for k,v in parts.items()]
        try: result=p.predict(parts,chosen['policy'],x,r)
        finally:
            for hook in hooks: hook.remove()
        self.assertEqual(sorted(calls), [('cell-3',4),('shared',5)])
        self.assertEqual(result['execution']['rows_processed'],len(x))
        self.assertEqual(sorted(i for call in result['execution']['calls'] for i in call['rows']),list(range(len(x))))
        with torch.no_grad():
            expected=torch.empty(9,2)
            mask=r!=3
            expected[mask]=parts['shared'](c.augment(x[mask],r[mask],4))
            expected[~mask]=parts['cell-3'](x[~mask])
        self.assertTrue(torch.equal(torch.tensor(result['probabilities']),expected.softmax(-1)))

    def test_late_invalid_route_rejects_before_any_head(self):
        chosen, parts=self.chosen(); routes=self.r.clone(); routes[-1]=4
        with patch.object(e.Head,'forward') as forward, self.assertRaises(e.InputError):
            p.predict(parts,chosen['policy'],torch.zeros(8,8),routes)
        forward.assert_not_called()

    def test_extra_component_and_changed_weights_rejected(self):
        chosen,parts=self.chosen()
        with self.assertRaises(e.InputError): p.predict({**parts,'cell-0':self.teachers[0]},chosen['policy'],torch.zeros(8,8),self.r)
        with torch.no_grad(): parts['shared'].base.bias.add_(1)
        with patch.object(e.Head,'forward') as forward, self.assertRaises(e.InputError):
            p.predict(parts,chosen['policy'],torch.zeros(8,8),self.r)
        forward.assert_not_called()

    def test_policy_identity_accounting_route_and_authority_drift_rejected(self):
        chosen,parts=self.chosen()
        for key,value in [('parameters',1),('parameter_bytes',0),('production_accepted',True),('assignment',['cell-1']*4)]:
            policy=deepcopy(chosen['policy']);policy[key]=value
            with self.assertRaises(e.InputError): p.predict(parts,policy,torch.zeros(8,8),self.r)

    def test_selected_bundle_contains_no_unused_teachers(self):
        chosen,parts=self.chosen()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'bundle'; seal=p.export(root,parts,chosen['policy'],self.bindings(parts))
            self.assertEqual({f.name for f in root.iterdir()},{'manifest.json','shared','cell-3'})
            reloaded,policy=p.reopen(root,seal)
            x=torch.randn(8,8)
            self.assertEqual(p.predict(parts,policy,x,self.r)['probabilities'],p.predict(reloaded,policy,x,self.r)['probabilities'])
            with self.assertRaises(FileExistsError): p.export(root,parts,policy,self.bindings(parts))
            with self.assertRaises(e.InputError): p.reopen(root,'0'*64)
            (root/'unused').mkdir()
            with self.assertRaises(e.InputError): p.reopen(root,seal)

    def test_late_rehashed_inventory_poison_rejects_before_any_model_load(self):
        chosen,parts=self.chosen()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'bundle'; p.export(root,parts,chosen['policy'],self.bindings(parts))
            doc=e.decode((root/'manifest.json').read_bytes())
            head=e.decode((root/'cell-3/manifest.json').read_bytes())
            head['parameters']['parameters']+=1
            raw=e.canonical(head); (root/'cell-3/manifest.json').write_bytes(raw)
            doc['heads']['cell-3']['manifest_sha256']=e.sha(raw)
            raw=e.canonical(doc); (root/'manifest.json').write_bytes(raw)
            with patch.object(p,'load_head') as load,self.assertRaises(e.InputError): p.reopen(root,e.sha(raw))
            load.assert_not_called()

    def test_scope_conflict_rejects_before_file_creation(self):
        chosen,parts=self.chosen(); b=self.bindings(parts); b['shared']['scope']='other'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'bundle'
            with self.assertRaises(e.InputError): p.export(root,parts,chosen['policy'],b)
            self.assertFalse(root.exists())

    def test_calibration_labels_or_cost_inventory_drift_rejects(self):
        for key,value in [('parameter_counts',{'bank':1}),('calibration_scores',{})]:
            rec=deepcopy(self.receipt);rec[key]=value
            with self.assertRaises(e.InputError): p.select(rec,self.y,self.r)
        with self.assertRaises(e.InputError): p.select(self.receipt,1-self.y,self.r)

    def test_fresh_process_runs_with_only_minimal_bundle(self):
        chosen,parts=self.chosen()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); seal=p.export(root/'bundle',parts,chosen['policy'],self.bindings(parts))
            save_file({'x':torch.randn(8,8),'r':self.r},root/'inputs.safetensors')
            code="""import sys,importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name.split('.')[0] in {'transformers','tokenizers','huggingface_hub'}: raise AssertionError(name)
sys.meta_path.insert(0,Block())
from pathlib import Path
from safetensors.torch import load_file
from experiments.shared_stem_cell import partial_consolidation as p,execution as e
root=Path(sys.argv[1]); parts,policy=p.reopen(root/'bundle',sys.argv[2])
x=load_file(root/'inputs.safetensors');e.write_once(root/'result.json',p.predict(parts,policy,x['x'],x['r']))
"""
            result=subprocess.run([sys.executable,'-c',code,str(root),seal],capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            self.assertEqual(e.decode((root/'result.json').read_bytes())['execution']['rows_processed'],8)

    def test_real_producer_integration_seals_before_selected_inference(self):
        from experiments.shared_stem_cell.test_feature_replay import FeatureReplayTests
        fixture=FeatureReplayTests('test_exact_tensor_roundtrip_without_raw_text_or_labels');fixture.setUp()
        try:
            _,digest=fixture.producer();out=fixture.root/'partial'
            before={f:f.read_bytes() for f in fixture.root.rglob('*') if f.is_file()}
            original=p.predict;count=0;step=torch.optim.AdamW.step
            def counted(opt,*args,**kw):
                nonlocal count
                count+=1;return step(opt,*args,**kw)
            def guarded(*args):
                self.assertTrue((out/'selection.json').exists());self.assertTrue((out/'partial-selection.json').exists())
                return original(*args)
            with patch.object(p,'predict',guarded),patch.object(torch.optim.AdamW,'step',counted),patch.object(e,'LocalEncoder') as enc:
                result=s.study(fixture.root/'manifest.json',fixture.root/'producer',digest,out,partial=True)
            enc.assert_not_called(); self.assertEqual(count,result['student_training_steps'])
            self.assertEqual(set(result['scores']['holdout']),{*c.ARMS,'partial_selected'})
            self.assertTrue(all(f.read_bytes()==raw for f,raw in before.items()))
            self.assertEqual(result['partial']['execution']['rows_processed'],4)
        finally: fixture.tearDown()


if __name__=='__main__':
    unittest.main()
