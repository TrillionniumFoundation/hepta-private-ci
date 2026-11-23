import unittest

import numpy as np

from . import reference


def make():
    r=np.random.default_rng(73)
    n=24
    rec=np.repeat(np.arange(6),4).astype(str)
    return dict(audio=r.normal(size=(n,6,52)),visual=r.normal(size=(n,6,76)),label=np.repeat([0,0,0,1,1,1],4),
                group=rec,recording=rec,start_seconds=np.tile([0,4,8,12],6),dt=np.full((n,6),.48),
                split=np.repeat('train',n),query_id=np.arange(n).astype(str))


class Reference(unittest.TestCase):
    def test_disjoint_intervals_true_slot_and_fold(self):
        data=make()
        p=reference.pairs(data)
        self.assertEqual(p.shape,(18,4))
        for q,l,r,t in p:
            self.assertEqual(data['recording'][[l,r][t]],data['recording'][q])
            self.assertEqual(data['label'][l],data['label'][r])
            self.assertTrue(data['start_seconds'][q]>=4)
        before=reference.crossfit(data,p)[0]
        # Perturb the unused later passages of the negative recording.
        negative=data['group'][p[0,2 if p[0,3]==0 else 1]]
        mask=(data['group']==negative)&(data['start_seconds']>0)
        data['audio'][mask]+=20
        after=reference.crossfit(data,p)[0]
        np.testing.assert_allclose(before['scores'][0],after['scores'][0])

    def test_plateau_sign_and_paid_isolation(self):
        data=make();p=reference.pairs(data)
        m=reference.metric(data,p,())
        x,paid=reference.build(data,p,m)
        swapped=p.copy();swapped[:,1:3]=p[:,[2,1]]
        y,_=reference.build(data,swapped,m)
        np.testing.assert_allclose(x['scores'][:,:,0],y['scores'][:,:,1])
        data['visual']+=np.arange(len(data['visual']))[:,None,None]*10.
        alt,pp=reference.build(data,p,m)
        np.testing.assert_allclose(x['x'],alt['x'])
        self.assertFalse(np.allclose(paid['handwritten_visual'],pp['handwritten_visual']))
