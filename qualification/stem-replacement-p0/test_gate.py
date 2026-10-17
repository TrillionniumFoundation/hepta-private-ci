"""Deterministic source/authority tests. All numbers are synthetic fixtures, NOT model evidence."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import gate


def fixture():
    cases = []
    for i, split in enumerate(('fit','fit','cal','cal','test','test','test','test')):
        cases.append({'case_id':f'case{i}', 'group_id':f'group{i//2 if split!="test" else i}',
                      'family_id':'synthetic-test', 'split':split,
                      'source_sha256':gate.digest(f'source{i//2 if split!="test" else i}'),
                      'input_sha256':gate.digest(f'question{i}'), 'token_count':32})
    # fit group0, cal group1, test groups4-7: disjoint source and groups.
    panel={'schema':gate.SCHEMA, 'source_revision':'a'*40, 'source_material_sha256':'b'*64,
           'purpose':'binary-support-research-only', 'budget':{'max_tokens':512,
                    'head_steps':40, 'head_trainable_params':4161, 'head_seed':41,
                    'head_optimizer':'sgd-lr-0.1','precision':'float32'},
           'cases':cases, 'authority':'DENY_ALL', 'production_promotion_permitted':False,
           'future_window_verified':False}
    seals=[]
    test_ids=[x['case_id'] for x in cases if x['split']=='test']
    for j,(model,(repo,rev,_,basis)) in enumerate(gate.MODELS.items()):
        preds=[{'case_id':cid,'p_positive':0.1+(k+j)*0.1} for k,cid in enumerate(test_ids)]
        seals.append({'schema':gate.SCHEMA,'model':model,'repo':repo,'revision':rev,'basis':basis,
                      'panel_sha256':gate.digest(panel),'artifact_weights_sha256':gate.digest(model),
                      'tokenizer_sha256':gate.digest(rev),'original_tensor_bytes_verified':True,
                      'trainable_params':4161 if basis=='head' else 0,
                      'optimizer_steps':40 if basis=='head' else 0,
                      'fit_rows':2 if basis=='head' else 0,
                      'encoder_calls':4,'load_wall_ns':10,'run_wall_ns':20,'peak_rss_bytes':400,
                      'predictions':preds,'predictions_sha256':gate.digest(preds),
                      'authority':'DENY_ALL','production_promotion_permitted':False})
    gold={'schema':gate.SCHEMA,'panel_sha256':gate.digest(panel), 'source_revision':'a'*40,
          'sealed_prediction_digests':{r['model']:r['predictions_sha256'] for r in seals},
          'original_gold_sha256':'c'*64,'test_targets':[{'case_id':cid,'label':i%2} for i,cid in enumerate(test_ids)]}
    return panel,seals,gold


class GateTests(unittest.TestCase):
    def assertDenied(self, panel, seals, gold):
        with self.assertRaises(gate.Denied):
            gate.evaluate(panel,seals,gold)

    def test_good_fixture_remains_no_go(self):
        p,r,g=fixture(); v=gate.evaluate(p,r,g)
        self.assertEqual(v['disposition'],'HOLD_NO_GO')
        self.assertIsNone(v['selected_model'])
        self.assertIs(v['promotion_permitted'],False)
        self.assertEqual(set(v['results']),set(gate.MODELS))
        self.assertEqual(v['results']['ettin400']['original_test_case_count'],4)
        self.assertEqual(v['results']['ettin400']['basis'],'head')

    def test_repeat_deterministic(self):
        self.assertEqual(gate.evaluate(*fixture()),gate.evaluate(*fixture()))

    def test_missing_arm(self):
        p,r,g=fixture();self.assertDenied(p,r[:-1],g)

    def test_duplicate_arm(self):
        p,r,g=fixture();r[-1]=copy.deepcopy(r[0]);self.assertDenied(p,r,g)

    def test_wrong_revision(self):
        p,r,g=fixture();r[2]['revision']='0'*40;self.assertDenied(p,r,g)

    def test_wrong_model_namespace(self):
        p,r,g=fixture();r[2]['repo']='attacker/ettin';self.assertDenied(p,r,g)

    def test_wrong_basis(self):
        p,r,g=fixture();r[2]['basis']='native';self.assertDenied(p,r,g)

    def test_forged_model_success_without_weights(self):
        p,r,g=fixture();r[2]['original_tensor_bytes_verified']=False;self.assertDenied(p,r,g)

    def test_forged_parameter_count(self):
        p,r,g=fixture();r[2]['trainable_params']=4160;self.assertDenied(p,r,g)

    def test_unpaid_optimizer(self):
        p,r,g=fixture();r[2]['optimizer_steps']=0;self.assertDenied(p,r,g)

    def test_fake_laya_training(self):
        p,r,g=fixture();r[0]['optimizer_steps']=40;self.assertDenied(p,r,g)

    def test_unobserved_encoder_or_cost(self):
        for k in ('encoder_calls','load_wall_ns','run_wall_ns','peak_rss_bytes'):
            with self.subTest(k=k):
                p,r,g=fixture();r[2][k]=0;self.assertDenied(p,r,g)

    def test_counterfeit_authority(self):
        p,r,g=fixture();r[0]['authority']='ALLOW';self.assertDenied(p,r,g)

    def test_counterfeit_promotion(self):
        p,r,g=fixture();r[1]['production_promotion_permitted']=True;self.assertDenied(p,r,g)

    def test_false_future_window(self):
        p,r,g=fixture();p['future_window_verified']=True;self.assertDenied(p,r,g)

    def test_leaked_label(self):
        p,r,g=fixture();p['cases'][0]['label']=1;self.assertDenied(p,r,g)

    def test_text_embedded_in_panel(self):
        p,r,g=fixture();p['cases'][0]['text']='secret';self.assertDenied(p,r,g)

    def test_cross_split_identical_original_source(self):
        p,r,g=fixture();p['cases'][4]['source_sha256']=p['cases'][0]['source_sha256'];self.assertDenied(p,r,g)

    def test_cross_split_same_group(self):
        p,r,g=fixture();p['cases'][4]['group_id']=p['cases'][0]['group_id'];self.assertDenied(p,r,g)

    def test_context_overflow(self):
        p,r,g=fixture();p['cases'][4]['token_count']=513;self.assertDenied(p,r,g)

    def test_prediction_late_mutation_without_reseal(self):
        p,r,g=fixture();r[2]['predictions'][0]['p_positive']=0.99;self.assertDenied(p,r,g)

    def test_prediction_rehash_invalidates_gold_seal(self):
        p,r,g=fixture();r[2]['predictions'][0]['p_positive']=0.99
        r[2]['predictions_sha256']=gate.digest(r[2]['predictions']);self.assertDenied(p,r,g)

    def test_swapped_output_identity(self):
        p,r,g=fixture();r[2]['predictions'][0]['case_id']=r[2]['predictions'][1]['case_id']
        r[2]['predictions_sha256']=gate.digest(r[2]['predictions']);self.assertDenied(p,r,g)

    def test_prediction_nan(self):
        p,r,g=fixture();r[0]['predictions'][0]['p_positive']=float('nan');self.assertDenied(p,r,g)

    def test_invalid_probability(self):
        p,r,g=fixture();r[2]['predictions'][0]['p_positive']=-1
        r[2]['predictions_sha256']=gate.digest(r[2]['predictions']);self.assertDenied(p,r,g)

    def test_missing_gold(self):
        p,r,g=fixture();g['test_targets']=g['test_targets'][:-1];self.assertDenied(p,r,g)

    def test_reordered_gold(self):
        p,r,g=fixture();g['test_targets'].reverse();self.assertDenied(p,r,g)

    def test_nonbinary_gold(self):
        p,r,g=fixture();g['test_targets'][0]['label']=2;self.assertDenied(p,r,g)

    def test_changed_source_identity(self):
        p,r,g=fixture();p['source_revision']='c'*40;self.assertDenied(p,r,g)

    def test_wrong_phase_original(self):
        p,r,g=fixture();g['sealed_prediction_digests']={};self.assertDenied(p,r,g)

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'bad.json';path.write_text('{"a":1,"a":2}',encoding='utf-8')
            with self.assertRaises(gate.Denied):gate.strict_load(path)

    def test_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'bad.json';path.write_text('{"x":NaN}',encoding='utf-8')
            with self.assertRaises(gate.Denied):gate.strict_load(path)

    def test_cli_separate_postseal_scoring_create_only(self):
        p,r,g=fixture()
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            for n,obj in (("panel",p),("sealed",r),("gold",g)):
                (d/(n+".json")).write_text(json.dumps(obj),encoding="utf-8")
            cmd=[sys.executable,str(Path(gate.__file__)), "--panel",str(d/"panel.json"),
                 "--sealed",str(d/"sealed.json"),"--gold",str(d/"gold.json"),
                 "--out",str(d/"summary.json")]
            process=subprocess.run(cmd,capture_output=True,text=True,check=False)
            self.assertEqual(process.returncode,0,process.stderr)
            obj=json.loads((d/"summary.json").read_text())
            self.assertEqual(obj["disposition"],"HOLD_NO_GO")
            self.assertEqual(obj["selected_model"],None)
            self.assertEqual(os.stat(d/"summary.json").st_mode & 0o077,0)
            again=subprocess.run(cmd,capture_output=True,text=True,check=False)
            self.assertNotEqual(again.returncode,0,"create-only output must reject overwrite")

    def test_cli_rejects_symlinked_gold(self):
        p,r,g=fixture()
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            for n,obj in (("panel",p),("sealed",r),("actual_gold",g)):
                (d/(n+".json")).write_text(json.dumps(obj),encoding="utf-8")
            (d/"gold.json").symlink_to(d/"actual_gold.json")
            with self.assertRaises(gate.Denied):
                gate.main(["--panel",str(d/"panel.json"),"--sealed",str(d/"sealed.json"),
                           "--gold",str(d/"gold.json"),"--out",str(d/"summary.json")])

    def test_malformed_nonhashable_model_rejected(self):
        p,r,g=fixture();r[1]['model']=[];self.assertDenied(p,r,g)

    def test_source_rebranded_as_independent_family(self):
        p,r,g=fixture();p['cases'][1]['family_id']='invented-new-publisher';self.assertDenied(p,r,g)

    def test_strict_input_size_budget(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'oversized.json'
            with path.open('wb') as f:
                f.truncate(16*1024*1024+1)
            with self.assertRaises(gate.Denied):gate.strict_load(path)

    def test_no_model_loader_or_mutator_api(self):
        self.assertFalse(hasattr(gate,'promote_model'))
        self.assertFalse(hasattr(gate,'select_model'))
        self.assertFalse(hasattr(gate,'load_model'))


if __name__ == '__main__':
    unittest.main()
