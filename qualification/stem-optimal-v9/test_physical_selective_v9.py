"""Synthetic numeric source-only negatives; original weights require hosted job."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import physical_selective_v9 as v9


def fixture():
    source={'schema':'hepta.stem.charge-stress.source.v3',
            'cohort':'hard-charge-four-intents-v3','heldout_labels_excluded':True,
            'production_authorized':False,
            'train':[{'case_id':f'fit:{i}', 'label':i%4,'text':f'train {i}'} for i in range(64)],
            'heldout':[{'case_id':f'heldout:{i}','source_sha256':f'{i:064x}',
                        'text':f'test {i}'} for i in range(32)]}
    source['source_plan_sha256']=v9.digest(v9.canonical(source))
    candidate={'repo':'example/granite47','revision':'d'*40,'weight_sha256':'f'*64}
    materials={'schema':'hepta.stem.original-candidate-model-material.v1',
               'research_only':True,'production_authorized':False,
               'training':{'seed':17,'steps':100,'learning_rate':0.006,
                           'per_cell_parameters':6914,'cells':4},
               'candidates':{'granite47':candidate}}
    rows=[]
    for i,r in enumerate(source['heldout']):
        margin=(i+1)/500
        rows.append({'case_id':r['case_id'],'source_sha256':r['source_sha256'],
                     'scores':{'char_345_tfidf_centroid':[0.5+margin,0.5-margin,0,0],
                               'word_12_tfidf_centroid':[0.7,0.3,0,0]}})
    cheap={'schema':'hepta.stem.hard-charge.lexical-control.v4',
           'source_plan_sha256':source['source_plan_sha256'],'rows':rows,
           'authority':'DENY_ALL','production_authorized':False,
           'cost':{'neural_encoder_forward_count':0}}
    old={'schema':'hepta.stem.charge-stress.physical-unattested.v3','candidate':'granite47',
         'source_plan_sha256':source['source_plan_sha256'],
         'authority':'DENY_ALL','production_authorized':False,
         'optimizer_steps':100,'head_parameters':27656,'model_repo':candidate['repo'],
         'model_revision':candidate['revision'],'actual_weight_sha256':candidate['weight_sha256'],
         'material_manifest_sha256':v9.digest(v9.canonical(materials)),
         'initial_head_sha256':'a'*64,'trained_head_sha256':'b'*64,
         'rows':[{'case_id':r['case_id'],'source_sha256':r['source_sha256'],
                  'scores':{'learned':[0.8,0.1,0.06,0.04]}} for r in source['heldout']]}
    return source,cheap,old,materials


class SampleModel:
    def __init__(self):
        import torch
        self.module=torch.nn.Linear(384,384,bias=False)
        self.register_forward_hook=self.module.register_forward_hook
    def __call__(self,inputs):
        return self.module(inputs)


def fake_encode(texts,tokenizer,model):
    import torch
    calls=0
    all_features=[]
    for offset in range(0,len(texts),16):
        chunk=texts[offset:offset+16]
        all_features.append(model(torch.full((len(chunk),384),.005)))
        calls+=1
    return torch.cat(all_features),calls


def fake_head(x,labels,queries,*,config):
    return {'total_head_parameters':27656, 'steps':100,
            'initial_head_sha256':'a'*64,'trained_head_sha256':'b'*64,
            'training_wall_seconds':0.01,
            'learned':[[0.8,0.1,0.06,0.04] for _ in range(len(queries))]}


class SelectivePhysicalSourceTests(unittest.TestCase):
    def setUp(self):
        self.source,self.cheap,self.old,self.materials=fixture()
        self.shapatch=patch.object(v9,'SOURCE_SHA',self.source['source_plan_sha256'])
        self.shapatch.start();self.addCleanup(self.shapatch.stop)

    def test_true_pytorch_hook_counts_on_8_and_32_without_test_gold(self):
        try:
            import torch
        except ImportError:
            self.skipTest('Torch fixture requires CPU wheel')
        stub=types.ModuleType('stem_candidate_v1')
        stub._material_model=lambda spec:(None,SampleModel())
        stub._encode=fake_encode
        stub._torch_head_training=fake_head
        stub._peak_rss_bytes=lambda:123456
        cheapmod=types.ModuleType('cheap_lexical_stem_v4')
        cheapmod.compute=lambda source:self.cheap
        with patch.dict(sys.modules,{'stem_candidate_v1':stub,
                                     'cheap_lexical_stem_v4':cheapmod}):
            a=v9.run('selective',self.source,self.cheap,self.old,self.materials)
            b=v9.run('full',self.source,self.cheap,self.old,self.materials)
        self.assertEqual((a['cost']['physically_executed_encoder_sequences'],
                          a['cost']['actual_model_forward_hook_calls']), (72,5))
        self.assertEqual((b['cost']['physically_executed_encoder_sequences'],
                          b['cost']['actual_model_forward_hook_calls']), (96,6))
        self.assertEqual((len(a['rows']),len(b['rows'])),(8,32))
        self.assertEqual(a['selected_case_ids'],b['selected_case_ids'])
        self.assertEqual(a['authority'],b['authority'])
        self.assertFalse(a['full_lifecycle_savings_qualified'])

    def test_source_and_heldout_label_smuggling_fail_closed(self):
        src=copy.deepcopy(self.source);src['heldout'][0]['label']=1
        with self.assertRaises(ValueError):v9.preflight(src,self.cheap,self.old,self.materials,'selective')
        src=copy.deepcopy(self.source);src['train'][0]['label']=3
        with self.assertRaisesRegex(ValueError,'source bytes changed'):
            v9.preflight(src,self.cheap,self.old,self.materials,'selective')

    def test_material_and_source_substitution_rejected(self):
        for name,mutate in [('weights',lambda m:m['candidates']['granite47'].__setitem__('weight_sha256','0'*64)),
                            ('steps',lambda m:m['training'].__setitem__('steps',1))]:
            with self.subTest(name=name):
                bad=copy.deepcopy(self.materials);mutate(bad)
                with self.assertRaises(ValueError):v9.preflight(self.source,self.cheap,self.old,bad,'full')

    def test_invalid_old_probability_and_wrong_mode_rejected(self):
        old=copy.deepcopy(self.old)
        old['rows'][0]['scores']['learned'][1]=float('nan')
        with self.assertRaisesRegex(ValueError,'invalid probability'):
            v9.preflight(self.source,self.cheap,old,self.materials,'full')
        with self.assertRaisesRegex(ValueError,'not a declared physical trial'):
            v9.preflight(self.source,self.cheap,self.old,self.materials,'stale')

    def test_altered_cheap_routing_probability_rejected(self):
        bad=copy.deepcopy(self.cheap)
        bad['rows'][0]['scores']['char_345_tfidf_centroid']=[0,0,0,0]
        with self.assertRaisesRegex(ValueError,'invalid probability'):
            v9.preflight(self.source,bad,self.old,self.materials,'selective')

    def test_offline_cost_must_not_claim_actual_energy_or_p99(self):
        chosen,lookup,old=v9.preflight(self.source,self.cheap,self.old,self.materials,'selective')
        self.assertEqual(len(chosen),8)
        self.assertEqual(len(lookup),len(old))
        self.assertEqual(chosen,sorted(chosen,key=lambda k:int(k.split(':')[1])))


if __name__=='__main__':unittest.main()
