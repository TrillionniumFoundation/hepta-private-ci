"""Research V16: concrete selected-row tests plus original-metadata tamper tests."""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
import torch
from torch import nn

import stem_specialization_v16 as p
import stem_specialization_v16_review as r


class Mechanism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_selected_head_physical_dispatch(self):
        split=p.make_split({"centers":torch.stack((torch.zeros(384),torch.ones(384))),
             **{f"heads.{k}.{n}":value for k in (0,1)
                for n,value in (("weight",torch.ones(4,384)),("bias",torch.zeros(4)))}})
        calls=[0,0]
        handles=[]
        for k,head in enumerate(split.heads):
            handles.append(head.register_forward_pre_hook(lambda m, a, k=k:calls.__setitem__(k,calls[k]+len(a[0]))))
        try:
            p.hard_head(split,torch.randn(16,384),torch.ones(16,dtype=torch.long))
        finally:
            for h in handles:h.remove()
        self.assertEqual(calls,[0,16])

    def test_soft_executes_both(self):
        model=p.make_split({"centers":torch.stack((torch.zeros(384),torch.ones(384))),
             **{f"heads.{k}.{n}":value for k in (0,1)
                for n,value in (("weight",torch.zeros(4,384)),("bias",torch.ones(4)*k))}})
        gate=p.make_gate()
        with torch.no_grad():
            out=p.soft_head(model,gate,torch.randn(8,384))
        self.assertTrue(torch.allclose(out,torch.full((8,4),.5)))

    def test_loss_targets_only_from_training(self):
        x=torch.randn(64,384)
        labels=torch.arange(64)%4
        model=p.make_split({"centers":torch.stack((x[0],x[1])),
             **{f"heads.{k}.{n}":value for k in (0,1)
                for n,value in (("weight",torch.randn(4,384)),("bias",torch.zeros(4)))}})
        w=p.fit_new_gate(p.make_gate(),x,labels,model,[list(range(16))]*2,objective='loss_target')
        self.assertEqual(w['examples'],32)
        self.assertEqual(w['source_train_rows'],64)

    def test_training_keeps_frozen_experts(self):
        x=torch.randn(64,384)
        y=torch.arange(64)%4
        state={"centers":torch.stack((x[0],x[1])),
             **{f"heads.{k}.{n}":value for k in (0,1)
                for n,value in (("weight",torch.randn(4,384)),("bias",torch.zeros(4)))}}
        split=p.make_split(state)
        before=p.v14.parameter_sha(split)
        p.fit_new_gate(p.make_gate(),x,y,split,[list(range(16))]*2,objective='expected_nll')
        self.assertEqual(before,p.v14.parameter_sha(split))

    def test_joint_uses_both_heads(self):
        x=torch.randn(64,384)
        y=torch.arange(64)%4
        parent=nn.Linear(384,4)
        split=p.v14.Split(parent,p.v14.fit_centers(x))
        w=p.train_joint(split,p.make_gate(),x,y,[list(range(16))]*2)
        self.assertEqual(w['train_symmetric_expert_forwards'],64)

    def test_budget_and_protocol(self):
        self.assertEqual(p.STEPS,80)
        self.assertEqual(p.PROTOCOL['new_pretrained_encoder_forwards'],0)
        self.assertFalse(p.PROTOCOL['production_authorized'])
        self.assertEqual(p.NAMES,r.NAMES)

    def test_selector_no_growth_tie(self):
        x={k:.5 for k in p.NAMES}
        self.assertEqual(p.choose(x,x),'frozen')
        self.assertEqual(r.candidate_select(x,x),'frozen')

    def test_selector_continuation_beats_split(self):
        scores=dict.fromkeys(p.NAMES,.7)
        scores.update(frozen=.8,continued=.6,loss_gate=.61)
        old=dict.fromkeys(p.NAMES,.4)
        self.assertEqual(p.choose(scores,old),'continued')

    def test_selector_growth_eligible(self):
        scores=dict.fromkeys(p.NAMES,.7)
        scores.update(frozen=.8,continued=.6,loss_gate=.2)
        old=dict.fromkeys(p.NAMES,.4)
        self.assertEqual(p.choose(scores,old),'loss_gate')

    def test_selector_old_task_veto(self):
        scores=dict.fromkeys(p.NAMES,.7)
        scores.update(frozen=.8,continued=.6,loss_gate=.2)
        old=dict.fromkeys(p.NAMES,.4)
        old['loss_gate']=.8
        self.assertEqual(p.choose(scores,old),'continued')

    def test_reject_invalid_training_rows(self):
        x=torch.ones(16,383)
        model=p.v14.Split(nn.Linear(384,4),torch.stack((torch.zeros(384),torch.ones(384))))
        with self.assertRaises(ValueError):p.fit_new_gate(p.make_gate(),x,torch.zeros(16,dtype=torch.long),model,[],objective='loss_target')

    def test_reviewer_separate(self):
        imports=[]
        tree=ast.parse(Path(r.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imports.extend(alias.name for alias in node.names)
            if isinstance(node,ast.ImportFrom):imports.append(node.module or '')
        self.assertFalse(any('stem' in x or 'torch' in x for x in imports))

    def test_create_only_wrong_model_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'missing'
            with self.assertRaises(ValueError):p.run(directory,directory,target)
            self.assertFalse(target.exists())

    def test_independent_soft_probability_math(self):
        x=np.array([[1,2,3,4]],dtype=float)
        self.assertAlmostEqual(float(r.brier(x/10,np.array([0]))),1.1,places=8)


@unittest.skipUnless(os.environ.get('HEPTA_V16_INPUTS') and os.environ.get('HEPTA_V16_V15'),
                     'real verified V15 originals not provisioned; NOT a research PASS')
class Original(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        cls.inputs=Path(os.environ['HEPTA_V16_INPUTS'])
        cls.v15=Path(os.environ['HEPTA_V16_V15'])
        cls.output=cls.root/'v16'
        p.run(cls.inputs,cls.v15,cls.output)
        cls.sealed=p.v14.read_json(cls.output/'sealed.json')
        cls.review=r.review(cls.inputs,cls.v15,cls.output)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def tamper(self,change):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'candidates'
            shutil.copytree(self.output,out)
            seal=deepcopy(self.sealed)
            change(seal,out)
            (out/'sealed.json').write_bytes(p.v14.canonical(seal))
            with self.assertRaises((ValueError,KeyError)):
                r.review(self.inputs,self.v15,out)

    def test_exact_15_model_files(self):
        self.assertEqual(self.review['model_files_verified'],15)
        self.assertEqual(self.review['v15_original_files_verified'],58)
        self.assertLess(self.review['max_probability_error'],5e-5)

    def test_no_blind_labels_read(self):
        self.assertIsNone(self.review['held_scores'])
        self.assertFalse(self.sealed['held_labels_read'])
        self.assertFalse(self.review['production_authorized'])

    def test_no_deployed_selection(self):
        self.assertTrue(all(row['selected_research_candidate'] in p.NAMES for row in self.sealed['seeds'].values()))
        self.assertFalse(self.sealed['target_host_4096_qualified'])

    def test_wrong_model_sha_denied(self):
        self.tamper(lambda s,o:s['model_files']['41-joint_gate'].__setitem__('sha256','0'*64))

    def test_rehashed_tensor_tamper_denied(self):
        def alter(s,o):
            f=o/'41-joint_gate.safetensors';raw=bytearray(f.read_bytes());raw[-1]^=1
            f.write_bytes(raw);s['model_files']['41-joint_gate']['sha256']=p.v14.sha(raw)
        self.tamper(alter)

    def test_false_CI_claim(self):
        self.tamper(lambda s,o:s.__setitem__('production_authorized',True))

    def test_fake_future_effect(self):
        self.tamper(lambda s,o:s.__setitem__('independent_future_utility',1.5))

    def test_fake_old_retain(self):
        self.tamper(lambda s,o:s.__setitem__('independent_negative_transfer',0))

    def test_fake_blind_score(self):
        self.tamper(lambda s,o:s.__setitem__('held_scores',{'accuracy':1.0}))

    def test_changed_calibration(self):
        self.tamper(lambda s,o:s['seeds']['47']['calibration']['loss_gate'].__setitem__('correct',32))

    def test_changed_blind_outputs(self):
        self.tamper(lambda s,o:s['seeds']['53']['blind_probabilities']['extra_continued'][0].__setitem__(0,.01))

    def test_changed_route(self):
        self.tamper(lambda s,o:s['seeds']['47']['calibration_routes']['joint_hard'].__setitem__(0,2))

    def test_changed_trainer_cost(self):
        self.tamper(lambda s,o:s['seeds']['41']['work']['joint'].__setitem__('train_symmetric_expert_forwards',0))

    def test_changed_diagnostic(self):
        self.tamper(lambda s,o:s['seeds']['41']['diagnostics'].__setitem__('v15_oof_vs_final_expert_direct_agreement',64))

    def test_selected_candidate_tamper(self):
        self.tamper(lambda s,o:s['seeds']['47'].__setitem__('selected_research_candidate','loss_gate'))

    def test_unregistered_file(self):
        self.tamper(lambda s,o:(o/'foreign.json').write_text('{}'))


if __name__=='__main__':unittest.main()
