import unittest
import numpy as np
from observed_output import Limits, EvidenceRejected, cvar90, compare

class ObservedOutputTests(unittest.TestCase):
    def setUp(self):
        self.z=np.full(11,-1.)
        self.limit=Limits(.4,.5,.5,.5,10.,.2,.4)
    def generate(self,x,w):
        y=(x['z']+w[0]*x['delta'])**2
        return {m:y for m in ('text','image','audio','video')}
    def score(self,raw,truth):
        err=(raw['text']-truth)**2
        return {'loss':err,'quality':(err<.01).astype(float),
                'ambiguity':np.zeros_like(err),'inconsistency':np.zeros_like(err)}
    def call(self,**over):
        d=dict(public_inputs={'z':self.z,'delta':np.full(11,2.)},hidden_labels=np.ones(11),
               episode_ids=[str(i) for i in range(11)],draw_episode_ids=[str(i) for i in range(11)],
               draws_per_episode=1,weights=[.5],generate=self.generate,
               independent_score=self.score,limits=self.limit,
               objective_digest='obj-1',model_digest='model-1',input_digest='cohort-1')
        d.update(over)
        return compare(**d)
    def test_actual_decode_rejects_loss_proxy_understatement(self):
        r=self.call()
        self.assertEqual(r['status'],'REJECT_OBSERVED_OUTPUT')
        self.assertEqual(r['baseline']['cvar90'],0.)
        self.assertEqual(r['selected']['cvar90'],1.)
        self.assertFalse(r['checks']['observed_cvar90'])
        self.assertEqual(r['authority'],'DENY_ALL')
    def test_endpoint_correct_still_never_authorizes(self):
        r=self.call(weights=[1.])
        self.assertEqual(r['status'],'ADVISORY_ONLY')
        self.assertFalse(r['independent_observer_authenticated'])
        self.assertFalse(r['scientific_efficacy_claim'])
    def test_fractional_tail(self):
        self.assertAlmostEqual(cvar90([0]*10+[10]),10/1.1)
        self.assertAlmostEqual(cvar90([0]*13+[4,10]),8.)
        self.assertEqual(cvar90([0]*19+[10]),5.)
    def test_missing_raw_modality_is_error(self):
        with self.assertRaisesRegex(EvidenceRejected,'modalities'):
            self.call(generate=lambda x,w: {'text':np.zeros(11)})
    def test_incomplete_scores_are_error(self):
        with self.assertRaisesRegex(EvidenceRejected,'scoring fields'):
            self.call(independent_score=lambda raw,truth:{'loss':np.zeros(11)})
    def test_nan_or_out_of_range_scores_rejected(self):
        def bad(raw,truth):
            r=self.score(raw,truth)
            r['quality'][:]=1.1
            return r
        with self.assertRaisesRegex(EvidenceRejected,'scoring dimension'):
            self.call(independent_score=bad)
    def test_mismatched_draw_episode_order_rejected(self):
        ids=[str(i%11) for i in range(44)]
        with self.assertRaisesRegex(EvidenceRejected,'unpaired'):
            self.call(public_inputs={'z':np.repeat(self.z,4),'delta':np.full(44,2.)},
                      hidden_labels=np.ones(44),draws_per_episode=4,draw_episode_ids=ids)
    def test_grouped_episode_cvar(self):
        ids=[str(i) for i in range(11) for _ in range(4)]
        r=self.call(public_inputs={'z':np.repeat(self.z,4),'delta':np.full(44,2.)},
                    hidden_labels=np.ones(44),draws_per_episode=4,draw_episode_ids=ids)
        self.assertEqual(r['selected']['cvar90'],1.)
        self.assertEqual(r['n_episodes'],11)
    def test_no_overbudget_cell_weights(self):
        with self.assertRaisesRegex(EvidenceRejected,'portfolio'):
            self.call(weights=[.8,.4])
    def test_hard_cost_rejects(self):
        lim=Limits(10.,0.,1.,1.,1e-16,1.,10.)
        r=self.call(limits=lim,weights=[1.])
        self.assertFalse(r['checks']['observed_generation_cost'])
        self.assertEqual(r['status'],'REJECT_OBSERVED_OUTPUT')

if __name__=='__main__':unittest.main()
