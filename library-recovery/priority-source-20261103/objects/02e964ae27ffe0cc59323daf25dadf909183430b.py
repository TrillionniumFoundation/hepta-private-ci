import unittest
import numpy as np
from p3_instance_retrieval_gate import inspect,MODALITIES


def make(n_holdout=5,n_train=3,collapsed=False):
    out=[]
    for split,n in (('train',n_train),('holdout',n_holdout)):
        for i in range(n):
            j=i if split=='holdout' else i+10
            v=np.zeros(20)
            v[j]=1.
            if collapsed:v=np.zeros(20);v[i%2]=1.
            out.append({'sample_id':f'{split}-{i}', 'split':split,
                        'entity_id':f'entity-{split}-{i}',
                        'scene_id':f'scene-{split}-{i}',
                        'embeddings':{m:v.tolist() for m in MODALITIES}})
    return out

class PairedRetrievalGate(unittest.TestCase):
    def test_true_instance_success_never_means_prod_pass(self):
        r=inspect(make())
        self.assertTrue(r['structurally_evaluable'])
        self.assertEqual(len(r['pair_directions']),12)
        self.assertTrue(r['all_directed_instance_top1_at_least_90pct'])
        self.assertFalse(r['true_natural_encoder_grounded'])
        self.assertFalse(r['production_evidence_accepted'])

    def test_class_shortcut_collapses_instance_and_is_rejected(self):
        r=inspect(make(collapsed=True))
        self.assertFalse(r['structurally_evaluable'])
        self.assertTrue(any('embedding collision' in s for s in r['issues']))
        self.assertFalse(r['all_directed_instance_top1_at_least_90pct'])

    def test_cross_split_entity_and_scene_reuse_blocked(self):
        s=make()
        s[0]['entity_id']=s[-1]['entity_id']
        s[1]['scene_id']=s[-2]['scene_id']
        r=inspect(s)
        self.assertFalse(r['structurally_evaluable'])
        self.assertTrue(any('cross-split entity' in k for k in r['issues']))
        self.assertTrue(any('cross-split scene' in k for k in r['issues']))

    def test_missing_modality_and_inf_blocked(self):
        s=make();del s[1]['embeddings']['audio']
        self.assertFalse(inspect(s)['structurally_evaluable'])
        s=make();s[1]['embeddings']['video'][0]=float('nan')
        self.assertFalse(inspect(s)['structurally_evaluable'])

    def test_cross_split_embedding_clone_rejected_even_with_distinct_metadata(self):
        s=make()
        for m in MODALITIES:
            s[0]['embeddings'][m]=s[-1]['embeddings'][m][:]
        r=inspect(s)
        self.assertFalse(r['structurally_evaluable'])
        self.assertTrue(any('cross-split embedding collision' in k for k in r['issues']))

    def test_true_corruption_fails_retrieval(self):
        r=inspect(make(n_holdout=9,n_train=3),noise_sigma=0.9)
        self.assertTrue(r['structurally_evaluable'])
        self.assertFalse(r['all_directed_instance_top1_at_least_90pct'])

if __name__=='__main__':unittest.main()
